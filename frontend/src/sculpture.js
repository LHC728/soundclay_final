import * as THREE from 'three'

const CONFIG = {
  sides: 10,
  baseParticles: 95,
  maxRadius: 2.35,
  pointSize: 0.082,
  maxPixelRatio: 1.35,
  targetFps: 45,
}

const clamp01 = (value) => Math.min(1, Math.max(0, value))

function seededRandom(seed) {
  const value = Math.sin(seed * 12.9898 + 78.233) * 43758.5453
  return value - Math.floor(value)
}

function buildGeometry() {
  const total = CONFIG.baseParticles * CONFIG.sides * 2
  const positions = new Float32Array(total * 3)
  const radii = new Float32Array(total)
  const angles = new Float32Array(total)
  const depths = new Float32Array(total)
  const phases = new Float32Array(total)
  const seeds = new Float32Array(total)

  const sectorAngle = (Math.PI * 2) / CONFIG.sides
  const halfSector = sectorAngle / 2
  let index = 0

  for (let base = 0; base < CONFIG.baseParticles; base += 1) {
    const radius = 0.12 + Math.sqrt(seededRandom(base + 1)) * (CONFIG.maxRadius - 0.12)
    const localAngle = seededRandom(base + 200) * halfSector
    const depth = (seededRandom(base + 400) - 0.5) * 0.62
    const phase = seededRandom(base + 600) * Math.PI * 2
    const seed = seededRandom(base + 800)

    for (let sector = 0; sector < CONFIG.sides; sector += 1) {
      const center = sector * sectorAngle

      for (let mirror = 0; mirror < 2; mirror += 1) {
        const angle = center + (mirror === 0 ? localAngle : -localAngle)
        const offset = index * 3

        positions[offset] = Math.cos(angle) * radius
        positions[offset + 1] = Math.sin(angle) * radius
        positions[offset + 2] = depth
        radii[index] = radius
        angles[index] = angle
        depths[index] = depth
        phases[index] = phase
        seeds[index] = (seed + sector / CONFIG.sides) % 1
        index += 1
      }
    }
  }

  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geometry.setAttribute('aRadius', new THREE.BufferAttribute(radii, 1))
  geometry.setAttribute('aAngle', new THREE.BufferAttribute(angles, 1))
  geometry.setAttribute('aDepth', new THREE.BufferAttribute(depths, 1))
  geometry.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1))
  geometry.setAttribute('aSeed', new THREE.BufferAttribute(seeds, 1))
  geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(), CONFIG.maxRadius * 2.2)
  return geometry
}

const vertexShader = /* glsl */ `
  precision highp float;

  uniform float uTime;
  uniform float uAudio;
  uniform float uMode;
  uniform float uPointerX;
  uniform float uPointerY;
  uniform float uEnergy;
  uniform float uBurst;
  uniform float uPointScale;
  uniform float uProgress;
  uniform float uState;

  attribute float aRadius;
  attribute float aAngle;
  attribute float aDepth;
  attribute float aPhase;
  attribute float aSeed;

  varying vec3 vColor;
  varying float vAlpha;

  vec3 palette(float t, float mode) {
    vec3 expressA = vec3(1.00, 0.20, 0.10);
    vec3 expressB = vec3(1.00, 0.72, 0.18);
    vec3 expressC = vec3(0.92, 0.14, 0.60);

    vec3 sootheA = vec3(0.62, 0.90, 1.00);
    vec3 sootheB = vec3(0.92, 0.98, 1.00);
    vec3 sootheC = vec3(0.55, 0.62, 1.00);

    float wave = 0.5 + 0.5 * sin(t * 6.2831853);
    vec3 express = mix(mix(expressA, expressB, wave), expressC, 0.28 + 0.22 * sin(t * 12.0));
    vec3 soothe = mix(mix(sootheA, sootheB, wave), sootheC, 0.22 + 0.18 * sin(t * 9.0));
    return mix(express, soothe, mode);
  }

  void main() {
    float radiusRatio = aRadius / ${CONFIG.maxRadius.toFixed(2)};
    float release = 1.0 - uMode;
    float calm = uMode;

    float speed = mix(1.24, 0.42, calm);
    float breathing = 1.0 + sin(uTime * speed + aPhase) * mix(0.072, 0.035, calm);
    float soundPush = uAudio * mix(0.50, 0.24, calm) * (0.24 + radiusRatio);
    float energyPush = (uEnergy - 0.5) * mix(0.50, 0.28, calm) * radiusRatio;
    float burstPush = uBurst * (0.34 + radiusRatio * 0.48);

    float sculptRadius = aRadius * breathing + soundPush + energyPush + burstPush;
    float turnSpeed = mix(0.14, 0.052, calm);
    float pointerTwist = uPointerX * radiusRatio * mix(0.72, 0.38, calm);
    float organicTwist = sin(uTime * mix(0.74, 0.35, calm) + aRadius * 2.6 + aPhase) * mix(0.055, 0.025, calm);
    float angle = aAngle + uTime * turnSpeed + pointerTwist + organicTwist;

    float vertical = uPointerY * 0.20 * (0.35 + radiusRatio);
    float ripple = sin(aRadius * 5.2 - uTime * mix(2.2, 0.7, calm) + aPhase) * mix(0.075, 0.035, calm);
    float depth = aDepth + ripple + vertical + uAudio * sin(aPhase) * 0.12;

    vec3 p = vec3(cos(angle) * sculptRadius, sin(angle) * sculptRadius, depth);

    float stageScale = mix(0.96, 1.05, smoothstep(0.0, 3.0, uState));
    p *= stageScale;

    vec4 mvPosition = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mvPosition;

    float perspective = uPointScale / max(-mvPosition.z, 0.2);
    float sizePulse = 1.0 + uAudio * 1.45 + uBurst * 0.75;
    gl_PointSize = ${CONFIG.pointSize.toFixed(3)} * perspective * sizePulse * mix(1.05, 0.88, radiusRatio);

    float colorT = fract(aSeed + uTime * mix(0.038, 0.014, calm) + uPointerX * 0.08 + uProgress * 0.04);
    vColor = palette(colorT, uMode);
    vColor *= 0.72 + 0.58 * (1.0 - radiusRatio) + uAudio * 0.42;
    vAlpha = mix(0.78, 0.96, 1.0 - radiusRatio) * (0.82 + uAudio * 0.18);
  }
`

const fragmentShader = /* glsl */ `
  precision highp float;

  varying vec3 vColor;
  varying float vAlpha;

  void main() {
    vec2 uv = gl_PointCoord - 0.5;
    float distanceToCenter = length(uv);
    float core = 1.0 - smoothstep(0.02, 0.48, distanceToCenter);
    float glow = 1.0 - smoothstep(0.12, 0.50, distanceToCenter);
    float alpha = (core * 0.68 + glow * 0.52) * vAlpha;

    if (alpha < 0.012) discard;
    gl_FragColor = vec4(vColor * (1.0 + core * 0.72), alpha);
  }
`

export function createSculpture(container) {
  if (!(container instanceof HTMLElement)) {
    throw new TypeError('createSculpture 需要有效的 HTMLElement 容器。')
  }

  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 100)
  camera.position.set(0, 0, 7.0)

  const renderer = new THREE.WebGLRenderer({
    antialias: false,
    alpha: true,
    powerPreference: 'high-performance',
    preserveDrawingBuffer: true,
  })

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, CONFIG.maxPixelRatio))
  renderer.setClearColor(0x000000, 0)
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.domElement.style.pointerEvents = 'none'
  container.replaceChildren(renderer.domElement)

  const geometry = buildGeometry()
  const uniforms = {
    uTime: { value: 0 },
    uAudio: { value: 0 },
    uMode: { value: 0.5 },
    uPointerX: { value: 0 },
    uPointerY: { value: 0 },
    uEnergy: { value: 0.5 },
    uBurst: { value: 0 },
    uPointScale: { value: 320 },
    uProgress: { value: 0 },
    uState: { value: 0 },
  }

  const material = new THREE.ShaderMaterial({
    uniforms,
    vertexShader,
    fragmentShader,
    transparent: true,
    depthWrite: false,
    depthTest: true,
    blending: THREE.AdditiveBlending,
  })

  const points = new THREE.Points(geometry, material)
  points.frustumCulled = false
  scene.add(points)

  const clock = new THREE.Clock()
  let frameId = 0
  let lastFrame = 0
  let destroyed = false
  let visible = true
  let frozen = false
  let visualTime = 0
  let audioTarget = 0
  let modeTarget = 0.5
  let xTarget = 0
  let yTarget = 0
  let energyTarget = 0.5
  let burstTarget = 0
  let stateTarget = 0
  let progressTarget = 0

  function resize() {
    const width = Math.max(1, container.clientWidth)
    const height = Math.max(1, container.clientHeight)
    camera.aspect = width / height
    camera.updateProjectionMatrix()
    renderer.setSize(width, height, false)
    uniforms.uPointScale.value = height * renderer.getPixelRatio() * 0.58
  }

  const resizeObserver = new ResizeObserver(resize)
  resizeObserver.observe(container)
  resize()

  function renderFrame(timestamp) {
    if (destroyed) return
    frameId = requestAnimationFrame(renderFrame)
    if (!visible) return

    const frameInterval = 1000 / CONFIG.targetFps
    if (timestamp - lastFrame < frameInterval) return
    lastFrame = timestamp - ((timestamp - lastFrame) % frameInterval)

    const delta = Math.min(clock.getDelta(), 0.05)
    if (!frozen) visualTime += delta

    uniforms.uTime.value = visualTime
    uniforms.uAudio.value += (audioTarget - uniforms.uAudio.value) * 0.22
    uniforms.uMode.value += (modeTarget - uniforms.uMode.value) * 0.08
    uniforms.uPointerX.value += (xTarget - uniforms.uPointerX.value) * 0.11
    uniforms.uPointerY.value += (yTarget - uniforms.uPointerY.value) * 0.11
    uniforms.uEnergy.value += (energyTarget - uniforms.uEnergy.value) * 0.10
    uniforms.uState.value += (stateTarget - uniforms.uState.value) * 0.08
    uniforms.uProgress.value += (progressTarget - uniforms.uProgress.value) * 0.16
    uniforms.uBurst.value += (burstTarget - uniforms.uBurst.value) * 0.22
    burstTarget *= 0.84

    points.rotation.x = uniforms.uPointerY.value * 0.14
    points.rotation.z = Math.sin(visualTime * 0.16) * 0.018
    renderer.render(scene, camera)
  }

  function onVisibilityChange() {
    visible = document.visibilityState === 'visible'
    if (visible) clock.getDelta()
  }

  document.addEventListener('visibilitychange', onVisibilityChange)
  frameId = requestAnimationFrame(renderFrame)

  return {
    setState(state) {
      const states = { idle: 0, recording: 1, mode: 2, sculpt: 3, result: 4 }
      stateTarget = states[state] ?? 0
    },

    setAudioLevel(level) {
      audioTarget = clamp01(Number(level) || 0)
    },

    setMode(value) {
      modeTarget = clamp01(Number(value) || 0)
    },

    setInteraction(x, y) {
      xTarget = THREE.MathUtils.clamp(Number(x) || 0, -1, 1)
      yTarget = THREE.MathUtils.clamp(Number(y) || 0, -1, 1)
      energyTarget = clamp01((1 - yTarget) * 0.5)
    },

    setProgress(value) {
      progressTarget = clamp01(Number(value) || 0)
    },

    burst(strength = 1) {
      burstTarget = Math.max(burstTarget, clamp01(Number(strength) || 1))
    },

    freeze(value) {
      frozen = Boolean(value)
    },

    async captureBlob() {
      renderer.render(scene, camera)
      return new Promise((resolve, reject) => {
        renderer.domElement.toBlob((blob) => {
          if (blob) resolve(blob)
          else reject(new Error('无法生成作品封面。'))
        }, 'image/png')
      })
    },

    destroy() {
      destroyed = true
      cancelAnimationFrame(frameId)
      resizeObserver.disconnect()
      document.removeEventListener('visibilitychange', onVisibilityChange)
      geometry.dispose()
      material.dispose()
      renderer.dispose()
      renderer.domElement.remove()
    },
  }
}
