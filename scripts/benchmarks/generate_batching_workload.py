#!/usr/bin/env python3
"""Write unique, seeded, round-trip verified 512-token completion prompts as JSONL."""
import argparse
import hashlib
import json
import random
from transformers import AutoTokenizer

p = argparse.ArgumentParser()
p.add_argument('--tokenizer', required=True)
p.add_argument('--count', type=int, default=30000)
p.add_argument('--seed', type=int, default=20261015)
a = p.parse_args()
t = AutoTokenizer.from_pretrained(a.tokenizer, local_files_only=True)
rng = random.Random(a.seed)
words = 'amber bridge cedar delta ember forest garden harbor island juniper lantern meadow north ocean pebble quartz river stone timber valley willow yellow zephyr'.split()
seen = set()
for i in range(a.count):
    nonce = hashlib.sha256(f'{a.seed}:{i}'.encode()).hexdigest()
    text = nonce + ' ' + ' '.join(rng.choices(words, k=650))
    ids = t.encode(text, add_special_tokens=False)[:512]
    prompt = t.decode(ids, skip_special_tokens=False)
    actual = len(t.encode(prompt, add_special_tokens=False))
    if actual != 512 or prompt in seen:
        raise RuntimeError(f'Invalid prompt {i}: {actual} tokens')
    seen.add(prompt)
    print(json.dumps({'id': i, 'prompt': prompt, 'input_tokens': actual, 'output_tokens': 128, 'seed': a.seed}), flush=True)
