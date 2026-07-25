import * as THREE from 'three'

const CONFIG = {
  sides: 10,
  baseParticles: 105,
  burstCopies: 7,
  maxRadius: 2.35,
  pointSize: 0.082,
  maxPixelRatio: 1.25,
  targetFps: 50,
  cameraZ: 8.6,
  cameraFov: 36,
  sphereViewportFill: 0.80,
  previewRotationSpeed: 1.15,
  previewRotationResponse: 7.5,
  maxRotationSpeed: 2.45,
  twistDeadZone: 0.055,
  twistTimeoutMs: 180,
  twistResponse: 12,
  sphereMorphResponse: 3.35,
  burstResponse: 3.65,
  sizeResponse: 4.6,
  minDepth: -5.4,
  maxDepth: 3.25,
  orientationResponse: 8.5,
  ambientRotationSpeed: 0.035,
}

const clamp01 = (value) => Math.min(1, Math.max(0, value))
const clampSigned = (value) => Math.min(1, Math.max(-1, value))
const finiteOr = (value, fallback = 0) => (Number.isFinite(Number(value)) ? Number(value) : fallback)

function seededRandom(seed) {
  const value = Math.sin(seed * 12.9898 + 78.233) * 43758.5453
  return value - Math.floor(value)
}

function gaussianLike(seedA, seedB, seedC) {
  return (
    seededRandom(seedA) +
    seededRandom(seedB) +
    seededRandom(seedC) -
    1.5
  ) / 1.5
}

function normalize3(x, y, z) {
  const length = Math.hypot(x, y, z) || 1
  return [x / length, y / length, z / length]
}

function buildGeometry() {
  // 主体仍是 105 × 10 × 2 = 2100 个万花筒粒子。
  // 每个主体粒子附带 7 个只在爆散时显现的电影碎屑，GPU 总粒子约 16800。
  // 碎屑在聚合时沿原轨迹收回并淡出，因此不会改变爆散前的球体结构。
  const mainTotal = CONFIG.baseParticles * CONFIG.sides * 2
  const total = mainTotal * (1 + CONFIG.burstCopies)
  const positions = new Float32Array(total * 3)
  const spherePositions = new Float32Array(total * 3)
  const burstDirections = new Float32Array(total * 3)
  const burstCurves = new Float32Array(total * 3)
  const radii = new Float32Array(total)
  const angles = new Float32Array(total)
  const depths = new Float32Array(total)
  const phases = new Float32Array(total)
  const seeds = new Float32Array(total)
  const burstDistances = new Float32Array(total)
  const debrisFlags = new Float32Array(total)
  const trailOffsets = new Float32Array(total)
  const burstDelays = new Float32Array(total)
  const particleSizes = new Float32Array(total)

  const sectorAngle = (Math.PI * 2) / CONFIG.sides
  const halfSector = sectorAngle / 2
  let index = 0
  let parentIndex = 0

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
        const radiusRatio = radius / CONFIG.maxRadius

        // 初始形态：原来的平面万花筒。
        const planeX = Math.cos(angle) * radius
        const planeY = Math.sin(angle) * radius
        const planeZ = depth

        // 球体形态：同一套万花筒映射到球面，主体代码保持不变。
        const sphereZ = 1 - 2 * radiusRatio * radiusRatio
        const sphereRing = Math.sqrt(Math.max(0, 1 - sphereZ * sphereZ))
        const shellNoise = 1 + depth * 0.075 + Math.sin(phase * 1.7) * 0.018
        const sphereX = Math.cos(angle) * sphereRing * shellNoise
        const sphereY = Math.sin(angle) * sphereRing * shellNoise
        const sphereDepth = sphereZ * shellNoise

        const normal = normalize3(sphereX, sphereY, sphereDepth)
        const parentTangent = normalize3(
          -Math.sin(angle),
          Math.cos(angle),
          gaussianLike(parentIndex + 9100, parentIndex + 9200, parentIndex + 9300) * 0.55,
        )
        const parentSideNoise = gaussianLike(parentIndex + 9400, parentIndex + 9500, parentIndex + 9600)
        const parentDirection = normalize3(
          normal[0] * 0.86 + parentTangent[0] * parentSideNoise * 0.52,
          normal[1] * 0.86 + parentTangent[1] * parentSideNoise * 0.52,
          normal[2] * 0.62 + gaussianLike(parentIndex + 9700, parentIndex + 9800, parentIndex + 9900) * 0.54,
        )
        const parentCurveSign = seededRandom(parentIndex + 10100) > 0.5 ? 1 : -1

        for (let copy = 0; copy <= CONFIG.burstCopies; copy += 1) {
          const isDebris = copy > 0
          const offset = index * 3
          const copySeed = parentIndex * 37 + copy * 991
          const trail = isDebris ? copy / (CONFIG.burstCopies + 1) : 0

          positions[offset] = planeX
          positions[offset + 1] = planeY
          positions[offset + 2] = planeZ
          spherePositions[offset] = sphereX
          spherePositions[offset + 1] = sphereY
          spherePositions[offset + 2] = sphereDepth

          // 主体粒子沿原有轨迹爆散；额外碎屑围绕该轨迹产生轻微角度差和更长飞行距离。
          const scatter = isDebris ? 0.18 + trail * 0.22 : 0
          const direction = normalize3(
            parentDirection[0] + gaussianLike(copySeed + 11, copySeed + 12, copySeed + 13) * scatter,
            parentDirection[1] + gaussianLike(copySeed + 21, copySeed + 22, copySeed + 23) * scatter,
            parentDirection[2] + gaussianLike(copySeed + 31, copySeed + 32, copySeed + 33) * scatter * 0.85,
          )
          const tangent = normalize3(
            parentTangent[0] + gaussianLike(copySeed + 41, copySeed + 42, copySeed + 43) * scatter * 0.55,
            parentTangent[1] + gaussianLike(copySeed + 51, copySeed + 52, copySeed + 53) * scatter * 0.55,
            parentTangent[2] + gaussianLike(copySeed + 61, copySeed + 62, copySeed + 63) * scatter,
          )
          const curveSign = isDebris
            ? (seededRandom(copySeed + 71) > 0.5 ? 1 : -1)
            : parentCurveSign
          const curveScale = isDebris
            ? 0.30 + seededRandom(copySeed + 81) * 0.46
            : 0.24 + seededRandom(parentIndex + 10200) * 0.32

          burstDirections[offset] = direction[0]
          burstDirections[offset + 1] = direction[1]
          burstDirections[offset + 2] = direction[2]
          burstCurves[offset] = tangent[0] * curveSign * curveScale
          burstCurves[offset + 1] = tangent[1] * curveSign * curveScale
          burstCurves[offset + 2] = tangent[2] * curveSign * curveScale * 0.72

          radii[index] = radius
          angles[index] = angle
          depths[index] = depth
          phases[index] = phase + (isDebris ? seededRandom(copySeed + 91) * 1.6 : 0)
          seeds[index] = isDebris ? seededRandom(copySeed + 101) : seed
          burstDistances[index] = isDebris
            ? 0.76 + seededRandom(copySeed + 111) * 1.15 + trail * 0.42
            : 0.48 + seededRandom(parentIndex + 10400) * 0.82
          debrisFlags[index] = isDebris ? 1 : 0
          trailOffsets[index] = trail
          burstDelays[index] = isDebris
            ? 0.018 + seededRandom(copySeed + 121) * 0.13 + trail * 0.055
            : 0
          particleSizes[index] = isDebris
            ? 0.30 + seededRandom(copySeed + 131) * 0.48
            : 1
          index += 1
        }

        parentIndex += 1
      }
    }
  }

  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geometry.setAttribute('aSpherePosition', new THREE.BufferAttribute(spherePositions, 3))
  geometry.setAttribute('aBurstDirection', new THREE.BufferAttribute(burstDirections, 3))
  geometry.setAttribute('aBurstCurve', new THREE.BufferAttribute(burstCurves, 3))
  geometry.setAttribute('aRadius', new THREE.BufferAttribute(radii, 1))
  geometry.setAttribute('aAngle', new THREE.BufferAttribute(angles, 1))
  geometry.setAttribute('aDepth', new THREE.BufferAttribute(depths, 1))
  geometry.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1))
  geometry.setAttribute('aSeed', new THREE.BufferAttribute(seeds, 1))
  geometry.setAttribute('aBurstDistance', new THREE.BufferAttribute(burstDistances, 1))
  geometry.setAttribute('aDebris', new THREE.BufferAttribute(debrisFlags, 1))
  geometry.setAttribute('aTrail', new THREE.BufferAttribute(trailOffsets, 1))
  geometry.setAttribute('aBurstDelay', new THREE.BufferAttribute(burstDelays, 1))
  geometry.setAttribute('aParticleSize', new THREE.BufferAttribute(particleSizes, 1))
  geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 60)
  return geometry
}

const vertexShader = /* glsl */ `
  precision highp float;

  uniform float uTime;
  uniform float uAudio;
  uniform float uMode;
  uniform float uSphereMorph;
  uniform float uSphereRadius;
  uniform float uBurst;
  uniform float uBurstTravel;
  uniform float uEnergy;
  uniform float uPointScale;
  uniform float uProgress;
  uniform float uState;
  uniform float uImpact;

  attribute vec3 aSpherePosition;
  attribute vec3 aBurstDirection;
  attribute vec3 aBurstCurve;
  attribute float aRadius;
  attribute float aAngle;
  attribute float aDepth;
  attribute float aPhase;
  attribute float aSeed;
  attribute float aBurstDistance;
  attribute float aDebris;
  attribute float aTrail;
  attribute float aBurstDelay;
  attribute float aParticleSize;

  varying vec3 vColor;
  varying float vAlpha;

  vec3 palette(float t, float mode) {
    // 两套配色沿用原项目：释放为暖色，舒缓为冷色。
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
    float calm = uMode;

    // 第一幕：持续呼吸的平面万花筒。
    float speed = mix(1.18, 0.40, calm);
    float breathing = 1.0 + sin(uTime * speed + aPhase) * mix(0.070, 0.032, calm);
    float soundPush = uAudio * mix(0.48, 0.22, calm) * (0.24 + radiusRatio);
    float energyPush = (uEnergy - 0.5) * mix(0.42, 0.24, calm) * radiusRatio;
    float kaleidoRadius = aRadius * breathing + soundPush + energyPush;
    float kaleidoRipple = sin(aRadius * 5.0 - uTime * mix(2.0, 0.68, calm) + aPhase)
      * mix(0.070, 0.032, calm);

    vec3 kaleido = vec3(
      cos(aAngle) * kaleidoRadius,
      sin(aAngle) * kaleidoRadius,
      aDepth + kaleidoRipple + uAudio * sin(aPhase) * 0.11
    );

    // 转腕后：同一批万花筒粒子包裹到 3D 球面。
    // 仅加入很小的切向流动与呼吸，球体主轮廓始终保持不变。
    vec3 sphereNormal = normalize(aSpherePosition);
    vec3 sphereTangent = normalize(vec3(-sphereNormal.y, sphereNormal.x, 0.22 + aDepth));
    float shellBreath = 1.0
      + sin(uTime * mix(0.72, 0.34, calm) + aPhase) * mix(0.018, 0.010, calm)
      + uAudio * mix(0.038, 0.020, calm);
    float surfaceFlow = sin(uTime * 0.66 + aPhase * 1.7 + aAngle * 2.0) * 0.020;
    vec3 sphere = aSpherePosition * uSphereRadius * shellBreath
      + sphereTangent * surfaceFlow * uSphereRadius;

    float sphereMorph = smoothstep(0.0, 1.0, uSphereMorph);
    vec3 p = mix(kaleido, sphere, sphereMorph);

    // 第二幕：快速挥动产生有弧度的爆散轨迹。
    // 第一次挥动让 uBurst 前进，第二次挥动让它沿同一路径回到 0。
    // 这是主动聚合，不是自动弹回。
    float burstEase = smoothstep(0.0, 1.0, min(uBurst, 1.0));
    float burstExtra = max(0.0, uBurst - 1.0);

    // 主体粒子立即爆开；电影碎屑带有极短延迟，并在同一轨迹后方形成连续尾迹。
    // 当第二次挥动使 uBurst 回到 0 时，这段计算会完整倒放，所有碎屑收回并淡出。
    float delayedBurst = mix(
      burstEase,
      smoothstep(aBurstDelay, 1.0, burstEase),
      aDebris
    );
    float trailStart = aTrail * 0.16;
    float trailBurst = clamp((delayedBurst - trailStart) / max(1.0 - trailStart, 0.01), 0.0, 1.0);
    trailBurst = smoothstep(0.0, 1.0, trailBurst);

    vec3 burstPath = aBurstDirection * trailBurst
      + aBurstCurve * trailBurst * trailBurst
      + aBurstDirection * burstExtra * 0.72 * mix(1.0, 1.18, aDebris);

    // 额外碎屑沿弧线外侧拉开，形成放射状颗粒流，而不是无规律噪点。
    vec3 cinematicArc = normalize(aBurstCurve + vec3(0.0001))
      * sin(trailBurst * 3.1415926)
      * aTrail
      * 0.12;
    float travelMultiplier = mix(1.0, 1.16 + aTrail * 0.52, aDebris);
    p += (burstPath + cinematicArc) * uBurstTravel * aBurstDistance * travelMultiplier;

    // 爆散后的主体与碎屑都保持轻微漂移，但不会自动回弹。
    float driftAmplitude = (0.012 + uAudio * 0.018) * uSphereRadius * trailBurst;
    p += aBurstCurve * sin(uTime * (0.78 + aTrail * 0.42) + aPhase) * driftAmplitude;

    // 第三幕的大小变化不在 Shader 中压扁或缩放粒子。
    // 整个 artworkGroup 会沿真实 Z 轴移动，因此万花筒球体结构始终保持不变。
    float stageScale = mix(0.96, 1.02, smoothstep(0.0, 3.0, uState));
    stageScale *= 1.0 + uImpact * 0.048;
    p *= stageScale;

    vec4 mvPosition = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mvPosition;

    float perspective = uPointScale / max(-mvPosition.z, 0.2);
    float impactSpark = 1.0 + uImpact * mix(0.55, 1.15, aDebris);
    float sizePulse = 1.0 + uAudio * 1.18 + burstEase * 0.10;
    float debrisSize = mix(1.0, aParticleSize * (0.84 + aTrail * 0.34), aDebris);
    gl_PointSize = ${CONFIG.pointSize.toFixed(3)}
      * perspective
      * sizePulse
      * impactSpark
      * debrisSize
      * mix(1.05, 0.88, radiusRatio);

    float colorT = fract(aSeed + uTime * mix(0.034, 0.012, calm) + uProgress * 0.04);
    vColor = palette(colorT, uMode);
    // 碎屑沿用同一套配色，只提升曝光，不换色。
    vColor *= 0.72
      + 0.58 * (1.0 - radiusRatio)
      + uAudio * 0.42
      + burstEase * 0.08
      + aDebris * (0.16 + uImpact * 0.30);

    float distanceFade = 1.0 - smoothstep(1.08, 1.92, length(p.xy) / max(uBurstTravel, 0.1));
    float mainAlpha = mix(0.78, 0.96, 1.0 - radiusRatio)
      * (0.82 + uAudio * 0.18)
      * mix(1.0, 0.78 + distanceFade * 0.22, burstEase);
    float debrisVisibility = smoothstep(0.012, 0.17, trailBurst);
    float debrisFlicker = 0.76 + 0.24 * sin(uTime * (7.0 + aTrail * 5.0) + aPhase * 2.2);
    float debrisAlpha = debrisVisibility
      * (0.26 + (1.0 - aTrail) * 0.48)
      * debrisFlicker
      * (0.72 + distanceFade * 0.28)
      * (1.0 + uImpact * 0.46);
    vAlpha = mix(mainAlpha, debrisAlpha, aDebris);
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
  const camera = new THREE.PerspectiveCamera(CONFIG.cameraFov, 1, 0.1, 100)
  camera.position.set(0, 0, CONFIG.cameraZ)

  const renderer = new THREE.WebGLRenderer({
    antialias: false,
    alpha: false,
    powerPreference: 'high-performance',
    preserveDrawingBuffer: true,
  })

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, CONFIG.maxPixelRatio))
  renderer.setClearColor(0x050505, 1)
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.domElement.style.pointerEvents = 'none'
  container.replaceChildren(renderer.domElement)

  const geometry = buildGeometry()
  const uniforms = {
    uTime: { value: 0 },
    uAudio: { value: 0 },
    uMode: { value: 0.5 },
    uSphereMorph: { value: 0 },
    uSphereRadius: { value: 2.35 },
    uBurst: { value: 0 },
    uBurstTravel: { value: 4.2 },
    uEnergy: { value: 0.5 },
    uPointScale: { value: 320 },
    uProgress: { value: 0 },
    uState: { value: 0 },
    uImpact: { value: 0 },
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

  // 所有粒子作为一个完整作品移动。大小变化只改变 Group.position.z，
  // 不修改粒子球的 scale，也不会压扁、凹陷或破坏万花筒结构。
  const artworkGroup = new THREE.Group()
  artworkGroup.add(points)
  scene.add(artworkGroup)

  const clock = new THREE.Clock()
  let frameId = 0
  let lastFrame = 0
  let destroyed = false
  let visible = true
  let frozen = false
  let currentState = 'idle'
  let visualTime = 0

  let previewRotationTarget = 0
  let previewRotationSmoothed = 0
  let twistTarget = 0
  let twistSmoothed = 0
  let twistPersistent = false
  let lastTwistInputAt = 0

  let sphereMorph = 0
  let sphereTarget = 0
  let burstAmount = 0
  let burstTarget = 0
  let burstExpanded = false

  // -1 = 左侧 / 小声 / 远处小球；1 = 右侧 / 大声 / 近处大球。
  let sizeControl = 0
  let sizeTarget = 0
  const depthCurrent = new THREE.Vector3(0, 0, 0)
  const depthTarget = new THREE.Vector3(0, 0, 0)

  let rotationX = 0
  let rotationY = 0
  let rotationZ = 0
  let orientationXTarget = 0
  let orientationYTarget = 0
  let orientationZTarget = 0
  let orientationXActive = false
  let orientationYActive = false
  let orientationZActive = false

  let audioTarget = 0
  let modeTarget = 0.5
  let energyTarget = 0.5
  let stateTarget = 0
  let progressTarget = 0
  let burstImpact = 0

  function resize() {
    const width = Math.max(1, container.clientWidth)
    const height = Math.max(1, container.clientHeight)
    camera.aspect = width / height
    camera.updateProjectionMatrix()
    renderer.setSize(width, height, false)

    const verticalVisible = 2 * Math.tan(THREE.MathUtils.degToRad(CONFIG.cameraFov * 0.5)) * CONFIG.cameraZ
    const horizontalVisible = verticalVisible * camera.aspect
    const smallerVisible = Math.min(verticalVisible, horizontalVisible)
    const largerVisible = Math.max(verticalVisible, horizontalVisible)

    // 球体占据短边约 86%，爆散轨迹覆盖长边并越过屏幕边缘。
    uniforms.uSphereRadius.value = smallerVisible * CONFIG.sphereViewportFill * 0.5
    uniforms.uBurstTravel.value = largerVisible * 0.72
    uniforms.uPointScale.value = height * renderer.getPixelRatio() * 0.58
  }

  const resizeObserver = new ResizeObserver(resize)
  resizeObserver.observe(container)
  resize()

  function normalizedTwist(value) {
    const input = clampSigned(Number(value) || 0)
    const magnitude = Math.abs(input)
    if (magnitude <= CONFIG.twistDeadZone) return 0
    const remapped = (magnitude - CONFIG.twistDeadZone) / (1 - CONFIG.twistDeadZone)
    return Math.sign(input) * Math.pow(remapped, 1.22)
  }

  function setPreviewRotation(value) {
    if (frozen) return
    previewRotationTarget = clampSigned(Number(value) || 0)
  }

  function setTwist(value, persistent = false) {
    if (frozen || currentState !== 'sculpt') return
    twistTarget = normalizedTwist(value)
    twistPersistent = Boolean(persistent) && twistTarget !== 0
    lastTwistInputAt = performance.now()

    // 第一次有效转腕把万花筒永久球化；之后不会回到平面。
    if (Math.abs(twistTarget) > 0.01) sphereTarget = 1
  }

  function setEnergy(value) {
    if (frozen) return
    energyTarget = clamp01(Number(value) || 0)
  }

  function setOrientation(orientation = {}) {
    if (frozen || currentState !== 'sculpt' || !orientation || typeof orientation !== 'object') return
    sphereTarget = 1

    // 预留戒指完整姿态接口。默认约定 roll / pitch / yaw 为弧度。
    // 若后端暂时只提供 twist，setTwist 仍可独立工作。
    if (Number.isFinite(Number(orientation.pitch))) {
      orientationXTarget = THREE.MathUtils.clamp(finiteOr(orientation.pitch), -Math.PI * 0.48, Math.PI * 0.48)
      orientationXActive = true
    }
    if (Number.isFinite(Number(orientation.yaw))) {
      orientationYTarget = finiteOr(orientation.yaw)
      orientationYActive = true
    }
    if (Number.isFinite(Number(orientation.roll))) {
      orientationZTarget = finiteOr(orientation.roll)
      orientationZActive = true
    }
  }

  function burst(strength = 1) {
    if (frozen || currentState !== 'sculpt') return null
    sphereTarget = 1
    burstExpanded = true

    // 快速挥动只向外爆散，不自动聚合或回弹。
    // 每次挥动会在已有结果上继续增加爆散距离，形成个性化作品。
    const amount = Math.max(0.16, Math.min(1.35, finiteOr(strength, 1)))
    burstTarget = Math.min(
      1.42,
      Math.max(burstTarget, burstAmount) + 0.24 + amount * 0.24,
    )
    burstImpact = Math.max(burstImpact, 0.72 + amount * 0.28)
    return 'explode'
  }

  function toggleBurst(strength = 1) {
    if (frozen || currentState !== 'sculpt') return null
    if (!burstExpanded) return burst(strength)

    burstExpanded = false
    burstTarget = 0
    burstImpact = 0
    sphereTarget = 1
    return 'restore'
  }

  function depthFromSize(value) {
    const normalized = (clampSigned(value) + 1) * 0.5
    // 使用 smoothstep 式缓动，让中段易控制，两端大小差异更明显。
    const eased = normalized * normalized * (3 - 2 * normalized)
    return THREE.MathUtils.lerp(CONFIG.minDepth, CONFIG.maxDepth, eased)
  }

  function setSize(value) {
    if (frozen || currentState !== 'sculpt') return sizeTarget
    sphereTarget = 1
    sizeTarget = clampSigned(finiteOr(value, 0))
    depthTarget.set(0, 0, depthFromSize(sizeTarget))
    return sizeTarget
  }

  function nudgeSize(delta = 0) {
    return setSize(sizeTarget + finiteOr(delta, 0))
  }

  // 保留旧 push / pull 接口，便于后端尚未更新时继续工作：
  // push = 推远变小，pull = 拉近变大。
  function push(strength = 1) {
    const amount = Math.max(0.08, Math.min(1.35, finiteOr(strength, 1)))
    nudgeSize(-amount * 0.52)
    return 'smaller'
  }

  function pull(strength = 1) {
    const amount = Math.max(0.08, Math.min(1.35, finiteOr(strength, 1)))
    nudgeSize(amount * 0.52)
    return 'larger'
  }

  function setDepthGesture(value) {
    return setSize(clampSigned(finiteOr(value, 0)))
  }

  function renderFrame(timestamp) {
    if (destroyed) return
    frameId = requestAnimationFrame(renderFrame)
    if (!visible) return

    const frameInterval = 1000 / CONFIG.targetFps
    if (timestamp - lastFrame < frameInterval) return
    lastFrame = timestamp - ((timestamp - lastFrame) % frameInterval)

    const delta = Math.min(clock.getDelta(), 0.05)

    if (!frozen) {
      visualTime += delta

      if (!twistPersistent && performance.now() - lastTwistInputAt > CONFIG.twistTimeoutMs) {
        twistTarget = 0
      }

      // 模式选择页：完整万花筒原地旋转，不提前球化。
      const previewBlend = 1 - Math.exp(-CONFIG.previewRotationResponse * delta)
      const previewTarget = currentState === 'mode' ? previewRotationTarget : 0
      previewRotationSmoothed += (previewTarget - previewRotationSmoothed) * previewBlend
      rotationZ -= previewRotationSmoothed * CONFIG.previewRotationSpeed * delta

      // 塑形页：转腕控制整体旋转；球体形状和万花筒纹理不被拉长。
      const twistBlend = 1 - Math.exp(-CONFIG.twistResponse * delta)
      twistSmoothed += (twistTarget - twistSmoothed) * twistBlend
      if (currentState === 'sculpt') {
        rotationZ -= twistSmoothed * CONFIG.maxRotationSpeed * delta
        // 极轻微的常速转动只用于持续生命感，不改变用户雕刻结果。
        rotationY += CONFIG.ambientRotationSpeed * delta * sphereMorph
      }

      const orientationBlend = 1 - Math.exp(-CONFIG.orientationResponse * delta)
      if (orientationXActive) rotationX += (orientationXTarget - rotationX) * orientationBlend
      if (orientationYActive) rotationY += (orientationYTarget - rotationY) * orientationBlend
      // roll 与 twist 都控制 z 轴：姿态值是绝对目标，twist 是相对增量。
      if (orientationZActive) rotationZ += (orientationZTarget - rotationZ) * orientationBlend * 0.18

      if (Math.abs(rotationX) > Math.PI * 8) rotationX %= Math.PI * 2
      if (Math.abs(rotationY) > Math.PI * 8) rotationY %= Math.PI * 2
      if (Math.abs(rotationZ) > Math.PI * 8) rotationZ %= Math.PI * 2

      const sphereBlend = 1 - Math.exp(-CONFIG.sphereMorphResponse * delta)
      const burstBlend = 1 - Math.exp(-CONFIG.burstResponse * delta)
      const depthBlend = 1 - Math.exp(-CONFIG.sizeResponse * delta)
      sphereMorph += (sphereTarget - sphereMorph) * sphereBlend
      burstAmount += (burstTarget - burstAmount) * burstBlend
      sizeControl += (sizeTarget - sizeControl) * depthBlend

      // Three.js Vector3.lerp：让整件作品沿 Z 轴平滑前后移动。
      // 停止手势后 depthTarget 不会重置，所以大小结果永久保留到凝固或重新开始。
      depthCurrent.lerp(depthTarget, depthBlend)
      artworkGroup.position.copy(depthCurrent)
      artworkGroup.scale.set(1, 1, 1)

      uniforms.uTime.value = visualTime
      uniforms.uAudio.value += (audioTarget - uniforms.uAudio.value) * (1 - Math.exp(-11 * delta))
      uniforms.uMode.value += (modeTarget - uniforms.uMode.value) * (1 - Math.exp(-5.2 * delta))
      uniforms.uSphereMorph.value = sphereMorph
      uniforms.uBurst.value = burstAmount
      uniforms.uEnergy.value += (energyTarget - uniforms.uEnergy.value) * (1 - Math.exp(-6.5 * delta))
      uniforms.uState.value += (stateTarget - uniforms.uState.value) * (1 - Math.exp(-5.2 * delta))
      uniforms.uProgress.value += (progressTarget - uniforms.uProgress.value) * (1 - Math.exp(-9 * delta))
      burstImpact *= Math.exp(-5.6 * delta)
      uniforms.uImpact.value = burstImpact
    }

    const impact = uniforms.uImpact.value
    points.position.set(
      Math.sin(visualTime * 53.0) * impact * 0.045,
      Math.cos(visualTime * 47.0) * impact * 0.034,
      Math.sin(visualTime * 39.0) * impact * 0.052,
    )
    artworkGroup.rotation.set(rotationX, rotationY, rotationZ)
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
      currentState = states[state] == null ? 'idle' : state
      stateTarget = states[currentState] ?? 0

      if (currentState !== 'mode') previewRotationTarget = 0
      if (currentState !== 'sculpt') {
        twistTarget = 0
        twistPersistent = false
      }
    },

    setAudioLevel(level) {
      if (frozen) return
      audioTarget = clamp01(Number(level) || 0)
    },

    setMode(value) {
      modeTarget = clamp01(Number(value) || 0)
    },

    setPreviewRotation,
    setTwist,
    setEnergy,
    setOrientation,
    burst,
    toggleBurst,
    setSize,
    nudgeSize,
    push,
    pull,
    setDepthGesture,

    // 鼠标普通拖动模拟转腕；大小由 setSize 单独控制。
    setInteraction(x, y) {
      if (currentState !== 'sculpt') return
      setTwist(x, true)
      orientationXTarget = clampSigned(Number(y) || 0) * -0.52
      setEnergy((1 - clampSigned(Number(y) || 0)) * 0.5)
    },

    setProgress(value) {
      if (frozen) return
      progressTarget = clamp01(Number(value) || 0)
    },

    freeze(value = true) {
      const next = Boolean(value)
      if (next === frozen) return
      frozen = next
      if (!frozen) {
        previewRotationTarget = 0
        previewRotationSmoothed = 0
        twistTarget = 0
        twistSmoothed = 0
        twistPersistent = false
        lastTwistInputAt = performance.now()
        clock.getDelta()
      }
    },

    reset() {
      frozen = false
      currentState = 'idle'
      visualTime = 0
      previewRotationTarget = 0
      previewRotationSmoothed = 0
      twistTarget = 0
      twistSmoothed = 0
      twistPersistent = false
      lastTwistInputAt = performance.now()
      sphereMorph = 0
      sphereTarget = 0
      burstAmount = 0
      burstTarget = 0
      burstExpanded = false
      sizeControl = 0
      sizeTarget = 0
      depthCurrent.set(0, 0, 0)
      depthTarget.set(0, 0, 0)
      rotationX = 0
      rotationY = 0
      rotationZ = 0
      orientationXTarget = 0
      orientationYTarget = 0
      orientationZTarget = 0
      orientationXActive = false
      orientationYActive = false
      orientationZActive = false
      audioTarget = 0
      energyTarget = 0.5
      progressTarget = 0
      burstImpact = 0
      uniforms.uTime.value = 0
      uniforms.uAudio.value = 0
      uniforms.uSphereMorph.value = 0
      uniforms.uBurst.value = 0
      uniforms.uEnergy.value = 0.5
      uniforms.uProgress.value = 0
      uniforms.uImpact.value = 0
      points.position.set(0, 0, 0)
      points.rotation.set(0, 0, 0)
      artworkGroup.position.set(0, 0, 0)
      artworkGroup.rotation.set(0, 0, 0)
      artworkGroup.scale.set(1, 1, 1)
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
