/**
 * Optional, fully synthesized crowd/bell audio — no files, no copyright, works
 * offline. Off by default; the header toggle flips `enabled`.
 */
let enabled = false
let ac: AudioContext | null = null

export function setSoundEnabled(v: boolean) { enabled = v }
export function isSoundEnabled() { return enabled }

function ctx(): AudioContext | null {
  if (!enabled) return null
  try {
    ac = ac ?? new (window.AudioContext || (window as any).webkitAudioContext)()
    if (ac.state === 'suspended') ac.resume()
    return ac
  } catch { return null }
}

/** The ring bell — three quick dings. */
function ding(c: AudioContext, t: number) {
  const o = c.createOscillator(), g = c.createGain()
  o.type = 'triangle'; o.frequency.value = 880
  g.gain.setValueAtTime(0.0001, t)
  g.gain.exponentialRampToValueAtTime(0.5, t + 0.005)
  g.gain.exponentialRampToValueAtTime(0.0001, t + 0.28)
  o.connect(g).connect(c.destination)
  o.start(t); o.stop(t + 0.3)
}

/** A short filtered-noise crowd swell. */
function crowd(c: AudioContext, t: number) {
  const dur = 1.1
  const buf = c.createBuffer(1, c.sampleRate * dur, c.sampleRate)
  const d = buf.getChannelData(0)
  for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1)
  const src = c.createBufferSource(); src.buffer = buf
  const f = c.createBiquadFilter(); f.type = 'bandpass'; f.frequency.value = 900; f.Q.value = 0.6
  const g = c.createGain()
  g.gain.setValueAtTime(0.0001, t)
  g.gain.exponentialRampToValueAtTime(0.22, t + 0.15)
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur)
  src.connect(f).connect(g).connect(c.destination)
  src.start(t); src.stop(t + dur)
}

/** Play when a show is run: bell then a crowd pop. */
export function playShow() {
  const c = ctx(); if (!c) return
  const t = c.currentTime
  ding(c, t); ding(c, t + 0.32); ding(c, t + 0.64)
  crowd(c, t + 0.7)
}

/** A single celebratory sting — used on a title change / crowning. */
export function playFanfare() {
  const c = ctx(); if (!c) return
  const t = c.currentTime
  ;[523, 659, 784, 1047].forEach((hz, i) => {
    const o = c.createOscillator(), g = c.createGain()
    o.type = 'sawtooth'; o.frequency.value = hz
    const s = t + i * 0.09
    g.gain.setValueAtTime(0.0001, s)
    g.gain.exponentialRampToValueAtTime(0.35, s + 0.02)
    g.gain.exponentialRampToValueAtTime(0.0001, s + 0.4)
    o.connect(g).connect(c.destination); o.start(s); o.stop(s + 0.42)
  })
}
