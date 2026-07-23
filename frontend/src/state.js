export const STATE_ORDER = [
  'ready',
  'recording',
  'understanding',
  'review',
  'choice',
  'materializing',
  'sculpting',
  'saved',
]

let currentState = 'ready'

export function getCurrentState() {
  return currentState
}

export function goToState(nextState) {
  if (!STATE_ORDER.includes(nextState)) {
    console.error(`Unknown state: ${nextState}`)
    return
  }

  currentState = nextState
}

export function nextState() {
  const currentIndex = STATE_ORDER.indexOf(currentState)

  if (currentIndex < STATE_ORDER.length - 1) {
    currentState = STATE_ORDER[currentIndex + 1]
  }
}

export function previousState() {
  const currentIndex = STATE_ORDER.indexOf(currentState)

  if (currentIndex > 0) {
    currentState = STATE_ORDER[currentIndex - 1]
  }
}

export function resetState() {
  currentState = 'ready'
}