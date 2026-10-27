"""15-minute typing drill for tomorrow's Runpod loop (Tue Oct 27, 9:00 AM CT).

Rebuilds, from scratch, the three patterns that wobbled in today's
Brody Kellish screen — async generator consumption, perf_counter deltas,
and asyncio.gather for a concurrency sweep — against a toy LLM like the
one in that screen. No external deps. Run: python drills/async_bench_drill.py

The point is muscle memory, not theory: type each pattern once tonight
so it comes to hand if another pad opens tomorrow.
"""

import asyncio
import time


async def toy_generate(prompt: str, n_tokens: int = 8):
    """Toy async token generator: yields one token at a time."""
    for i in range(n_tokens):
        await asyncio.sleep(0.01)  # stands in for decode latency
        yield f"tok{i}"


async def measure_one(prompt: str):
    """Return (ttft_s, itls, throughput_tok_per_s) for one request.

    First interval from start -> first token = TTFT.
    Every later interval = ITL. Throughput = tokens / total time.
    """
    start = time.perf_counter()
    ttft = None
    itls = []
    prev = start
    n_tokens = 0
    async for _token in toy_generate(prompt):  # <-- the async-for pattern
        now = time.perf_counter()
        if ttft is None:
            ttft = now - start
        else:
            itls.append(now - prev)
        prev = now
        n_tokens += 1
    total = time.perf_counter() - start
    return ttft, itls, n_tokens / total


async def sweep(prompts):
    """Run one prompt per concurrency level with asyncio.gather."""
    for concurrency in (1, 2, 4, 8):
        results = await asyncio.gather(
            *(measure_one(p) for p in prompts[:concurrency])
        )
        ttfts = [r[0] for r in results]
        throughputs = [r[2] for r in results]
        print(
            f"concurrency={concurrency}: "
            f"TTFT mean={sum(ttfts) / len(ttfts):.3f}s, "
            f"aggregate tok/s={sum(throughputs):.1f}"
        )


async def main():
    prompts = [f"explain AI inference in simple terms, variant {i}" for i in range(8)]
    ttft, itls, tps = await measure_one(prompts[0])
    print(f"single: TTFT={ttft:.3f}s, mean ITL={sum(itls) / len(itls):.3f}s, "
          f"throughput={tps:.1f} tok/s")
    await sweep(prompts)


if __name__ == "__main__":
    asyncio.run(main())
