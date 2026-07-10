import sys, json
from fastembed import TextEmbedding

model = TextEmbedding()

for line in sys.stdin:
    text = line.strip()
    if not text:
        continue
    vec = list(model.embed([text]))[0]
    # Convert to list of floats, then to buffer bytes
    import struct
    data = struct.pack(f'{len(vec)}f', *vec)
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()
