"""Optional idempotent one-way export to an existing Notion data source."""
import os
import httpx
from store import rows,event


def sync():
    token=os.environ.get('NOTION_TOKEN')
    source=os.environ.get('NOTION_DATA_SOURCE_ID')
    if not token or not source:
        raise ValueError('Set NOTION_TOKEN and NOTION_DATA_SOURCE_ID locally before syncing')
    headers={'Authorization':'Bearer '+token,'Notion-Version':'2025-09-03'}
    results=[]
    with httpx.Client(base_url='https://api.notion.com/v1',headers=headers,timeout=30,trust_env=False) as client:
        schema=client.get('/data_sources/'+source)
        schema.raise_for_status()
        props=schema.json()['properties']
        title=next((k for k,v in props.items() if v['type']=='title'),None)
        if not title or props.get('URL',{}).get('type')!='url':
            raise ValueError('Notion data source needs a title property and a URL property of type url')
        for item in rows('SELECT * FROM jobs'):
            properties={title:{'title':[{'text':{'content':(item['company']+' — '+item['title'])[:1900]}}]},'URL':{'url':item['url']}}
            for key,value in [('Company',item['company']),('Role',item['title']),('Stage',item['status'])]:
                if props.get(key,{}).get('type')=='rich_text':properties[key]={'rich_text':[{'text':{'content':str(value)[:1900]}}]}
            if props.get('Score',{}).get('type')=='number':properties['Score']={'number':item['score']}
            lookup=client.post('/data_sources/'+source+'/query',json={'filter':{'property':'URL','url':{'equals':item['url']}},'page_size':2})
            lookup.raise_for_status()
            matches=lookup.json()['results']
            if len(matches)>1:
                results.append({'job_id':item['id'],'status':'duplicate Notion rows; review manually'});continue
            if matches:
                response=client.patch('/pages/'+matches[0]['id'],json={'properties':properties})
            else:
                response=client.post('/pages',json={'parent':{'type':'data_source_id','data_source_id':source},'properties':properties})
            response.raise_for_status()
            results.append({'job_id':item['id'],'status':'synced','page_id':response.json()['id']})
    event('notion_sync',f'{len(results)} jobs processed')
    return results
