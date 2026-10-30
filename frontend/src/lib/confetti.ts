import confetti from "canvas-confetti"

export function triggerWinConfetti() {
  // Dual-cannon golden/emerald celebration for betting wins
  const count = 180
  const defaults = {
    origin: { y: 0.75 },
    zIndex: 9999,
  }

  function fire(particleRatio: number, opts: confetti.Options) {
    confetti({
      ...defaults,
      ...opts,
      particleCount: Math.floor(count * particleRatio),
    })
  }

  fire(0.25, {
    spread: 26,
    startVelocity: 55,
    colors: ["#10b981", "#34d399", "#fbbf24"],
  })
  fire(0.2, {
    spread: 60,
    colors: ["#f59e0b", "#d97706", "#10b981"],
  })
  fire(0.35, {
    spread: 100,
    decay: 0.91,
    scalar: 0.8,
    colors: ["#ffffff", "#6ee7b7", "#fef08a"],
  })
  fire(0.1, {
    spread: 120,
    startVelocity: 25,
    decay: 0.92,
    scalar: 1.2,
  })
}
