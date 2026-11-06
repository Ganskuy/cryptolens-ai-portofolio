"""Explicit bounded multi-year backfill into the configured CryptoLens database."""
import argparse
import asyncio

import httpx

from app.db import now
from app.providers import Provider, backfill
from app.registry import ASSETS
from app.worker import save_candles


async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--asset',choices=[a[0] for a in ASSETS],required=True)
    parser.add_argument('--days',type=int,default=730)
    args=parser.parse_args()
    if not 366<=args.days<=1826:
        raise SystemExit('Choose 366–1826 days')
    pair=next(a[3] for a in ASSETS if a[0]==args.asset)
    end=int(now().timestamp())//86400*86400
    async with httpx.AsyncClient() as client:
        rows=await backfill(Provider(client),pair,'1d',end-args.days*86400,end)
    await asyncio.to_thread(save_candles,args.asset,rows,'binance')
    print({'asset':args.asset,'finalized_rows':len(rows),'requested_days':args.days})


if __name__=='__main__':
    asyncio.run(main())
