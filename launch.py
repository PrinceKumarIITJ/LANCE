import asyncio
import sys
import uvicorn

if __name__=='__main__':
    if sys.platform=='win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    print('LANCE: http://127.0.0.1:8765 — keep this process running for scheduled work.')
    uvicorn.run('app:app',host='127.0.0.1',port=8765,loop='asyncio')
