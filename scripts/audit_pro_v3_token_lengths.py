"""Gap F — verify pro-v3 stays under the 4K context window for Gemma 4."""
import json, sys
from datasets import load_from_disk
from transformers import AutoTokenizer

# gpt2 tokenizer is conservative (slightly over-counts vs Gemma); ungated
tok = AutoTokenizer.from_pretrained("gpt2")

ds = load_from_disk("/Users/rahulrajpurohit/IdeaProjects/lysos/data/processed/amr-stage2-pro-v3")
LIMIT = 4096
WARN = 3200

n_total = 0
n_over = 0
n_warn = 0
hist = [0] * 8  # 0-512, 512-1024, 1024-1536, 1536-2048, 2048-2560, 2560-3200, 3200-4096, >4096

for split in ("train", "valid"):
    for row in ds[split]:
        n_total += 1
        msgs = row["messages"]
        if isinstance(msgs, str):
            try: msgs = json.loads(msgs)
            except: continue
        text = ""
        for m in msgs:
            c = m.get("content")
            if isinstance(c, str): text += c + "\n"
            elif isinstance(c, list):
                for b in c:
                    if isinstance(b, dict):
                        if isinstance(b.get("text"), str): text += b["text"] + "\n"
                        elif isinstance(b.get("content"), str): text += b["content"] + "\n"
                        else: text += json.dumps(b)[:1500] + "\n"
        n = len(tok.encode(text, add_special_tokens=False))
        if n > LIMIT: n_over += 1
        elif n > WARN: n_warn += 1
        bucket = min(7, n // 512)
        hist[bucket] += 1

print(f"Scanned {n_total:,} rows")
print(f"Over 4096 tokens: {n_over:,} ({100*n_over/n_total:.3f}%)")
print(f"Warn 3200-4096:   {n_warn:,} ({100*n_warn/n_total:.3f}%)")
print()
print("Distribution:")
labels = ["0-512", "512-1k", "1k-1.5k", "1.5k-2k", "2k-2.5k", "2.5k-3.2k", "3.2k-4k", ">4k"]
for L, h in zip(labels, hist):
    bar = "█" * int(50 * h / max(1, max(hist)))
    print(f"  {L:>10s}: {h:>8,}  {bar}")
