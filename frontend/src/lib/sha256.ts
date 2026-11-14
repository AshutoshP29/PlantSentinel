// Minimal synchronous SHA-256 (hex). Used to avoid keeping demo passwords in plain text
// in the browser. Works over plain http too, where crypto.subtle is unavailable.
// Real password checks belong on the backend.

export function sha256(text: string): string {
  const bytes = new TextEncoder().encode(text)
  const rotr = (v: number, n: number) => (v >>> n) | (v << (32 - n))
  const maxWord = 2 ** 32

  const hash: number[] = []
  const k: number[] = []
  const composite: Record<number, boolean> = {}
  for (let candidate = 2, found = 0; found < 64; candidate++) {
    if (!composite[candidate]) {
      for (let i = 0; i < 313; i += candidate) composite[i] = true
      hash[found] = (candidate ** 0.5 * maxWord) | 0
      k[found++] = (candidate ** (1 / 3) * maxWord) | 0
    }
  }

  const data = [...bytes, 0x80]
  while (data.length % 64 !== 56) data.push(0)
  const words: number[] = []
  for (let i = 0; i < data.length; i++) words[i >> 2] = (words[i >> 2] ?? 0) | (data[i] << ((3 - (i % 4)) * 8))
  const bitLength = bytes.length * 8
  words.push((bitLength / maxWord) | 0, bitLength | 0)

  let h = hash.slice(0, 8)
  for (let j = 0; j < words.length; j += 16) {
    const w = words.slice(j, j + 16)
    const old = h
    h = h.slice(0, 8)
    for (let i = 0; i < 64; i++) {
      if (i >= 16) {
        const w15 = w[i - 15]
        const w2 = w[i - 2]
        w[i] = (w[i - 16] + (rotr(w15, 7) ^ rotr(w15, 18) ^ (w15 >>> 3)) + w[i - 7] + (rotr(w2, 17) ^ rotr(w2, 19) ^ (w2 >>> 10))) | 0
      }
      const a = h[0]
      const e = h[4]
      const t1 = h[7] + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & h[5]) ^ (~e & h[6])) + k[i] + w[i]
      const t2 = (rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & h[1]) ^ (a & h[2]) ^ (h[1] & h[2]))
      h = [(t1 + t2) | 0, ...h]
      h[4] = (h[4] + t1) | 0
    }
    for (let i = 0; i < 8; i++) h[i] = (h[i] + old[i]) | 0
  }

  let out = ''
  for (let i = 0; i < 8; i++) for (let j = 3; j >= 0; j--) out += ((h[i] >>> (j * 8)) & 255).toString(16).padStart(2, '0')
  return out
}
