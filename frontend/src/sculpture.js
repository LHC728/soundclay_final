import * as THREE from 'three'

const CONFIG = {
  sides: 10,
  baseParticles: 105,
  maxRadius: 2.35,
  pointSize: 0.082,
  maxPixelRatio: 1.35,
  targetFps: 50,
  cameraZ: 8.6,
  cameraFov: 36,
  ribbonViewportFill: 0.94,
  // 选择模式预览：滑块越靠边，完整万花筒旋转越快。
  previewRotationSpeed: 1.15,
  previewRotationResponse: 7.5,
  maxRotationSpeed: 2.15,
  ribbonTwistSpeed: 1.35,
  twistDeadZone: 0.055,
  twistTimeoutMs: 180,
  twistResponse: 12,
  ribbonMorphResponse: 2.8,
}

const clamp01 = (value) => Math.min(1, Math.max(0, value))
const clampSigned = (value) => Math.min(1, Math.max(-1, value))

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

function buildGeometry() {
  // 仍然是原来的数量：105 × 10 × 2 = 2100 个粒子。
  const total = CONFIG.baseParticles * CONFIG.sides * 2
  const positions = new Float32Array(total * 3)
  const radii = new Float32Array(total)
  const angles = new Float32Array(total)
  const depths = new Float32Array(total)
  const phases = new Float32Array(total)
  const seeds = new Float32Array(total)

  // 同一批粒子在“转腕后”的稳定条带目标坐标。
  const ribbonU = new Float32Array(total)
  const ribbonV = new Float32Array(total)
  const ribbonZ = new Float32Array(total)

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

        // 初始位置保持原来的万花筒。
        positions[offset] = Math.cos(angle) * radius
        positions[offset + 1] = Math.sin(angle) * radius
        positions[offset + 2] = depth
        radii[index] = radius
        angles[index] = angle
        depths[index] = depth
        phases[index] = phase
        seeds[index] = seed

        // 条带沿整块画布横向铺开。两端自然收窄，中间更丰厚。
        const u = seededRandom(index + 1200) * 2 - 1
        const edgeTaper = Math.pow(Math.max(0, 1 - Math.abs(u)), 0.34)
        const thickness = gaussianLike(index + 2200, index + 3200, index + 4200)
        const depthCloud = gaussianLike(index + 5200, index + 6200, index + 7200)

        ribbonU[index] = u
        ribbonV[index] = thickness * edgeTaper
        ribbonZ[index] = depthCloud * edgeTaper
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
  geometry.setAttribute('aRibbonU', new THREE.BufferAttribute(ribbonU, 1))
  geometry.setAttribute('aRibbonV', new THREE.BufferAttribute(ribbonV, 1))
  geometry.setAttribute('aRibbonZ', new THREE.BufferAttribute(ribbonZ, 1))
  geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 20)
  return geometry
}

const vertexShader = /* glsl */ `
  precision highp float;

  uniform float uTime;
  uniform float uAudio;
  uniform float uMode;
  uniform float uTwist;
  uniform float uRibbonTwist;
  uniform float uRibbonMorph;
  uniform float uRibbonHalfWidth;
  uniform float uEnergy;
  uniform float uPointScale;
  uniform float uProgress;
  uniform float uState;
  uniform float uScatter;
  uniform float uAggregate;
  uniform float uDent;
  uniform float uPull;

  attribute float aRadius;
  attribute float aAngle;
  attribute float aDepth;
  attribute float aPhase;
  attribute float aSeed;
  attribute float aRibbonU;
  attribute float aRibbonV;
  attribute float aRibbonZ;

  varying vec3 vColor;
  varying float vAlpha;

  vec3 palette(float t, float mode) {
    // 颜色体系完全沿用原项目。
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

    // 1. 初始万花筒：保持原形态与原有呼吸感。
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

    // 2. 转腕后目标形态：贯穿画布的粒子条带 / 横向星云。
    float u = aRibbonU;
    float edgeTaper = pow(max(0.0, 1.0 - abs(u)), 0.34);

    // 条带中心线有大波浪与细波纹，但不是规则矩形。
    float centerWave =
      sin(u * 4.65 + 0.35) * 0.24 +
      sin(u * 10.8 + aPhase * 0.22) * 0.055;

    float ribbonX = u * uRibbonHalfWidth;
    float ribbonY = centerWave + aRibbonV * 0.58 + sin(aPhase + uTime * 0.30) * 0.025;
    float ribbonZ = aRibbonZ * 0.72 + sin(u * 8.2 + aPhase) * 0.045;

    // 声音只让条带轻微呼吸，不会改变粒子数量或主轮廓。
    ribbonY *= 1.0 + uAudio * 0.10;
    ribbonZ += uAudio * sin(aPhase) * 0.075;

    // 沿条带长度方向做立体扭转。
    float localTwistAngle = uRibbonTwist * u * 1.55;
    float cosTwist = cos(localTwistAngle);
    float sinTwist = sin(localTwistAngle);
    float twistedY = ribbonY * cosTwist - ribbonZ * sinTwist;
    float twistedZ = ribbonY * sinTwist + ribbonZ * cosTwist;

    vec3 ribbon = vec3(ribbonX, twistedY, twistedZ);

    // 第一次明显转腕后平滑展开；之后保持条带，不回到万花筒。
    float morph = smoothstep(0.0, 1.0, uRibbonMorph);
    vec3 p = mix(kaleido, ribbon, morph);

    // 爆散、聚合、压凹和拉起共享同一批粒子并平滑过渡。
    float scatterScale = 1.0 + uScatter * (0.58 + aSeed * 0.72);
    p.xy *= scatterScale;
    p.z += uScatter * sin(aPhase * 2.0 + aSeed * 8.0) * 0.72;

    p.x *= 1.0 - uAggregate * 0.30;
    p.y *= 1.0 + uAggregate * 0.22;
    p.z *= 1.0 - uAggregate * 0.34;

    float dentProfile = pow(max(0.0, 1.0 - radiusRatio), 1.35);
    p.y *= 1.0 - uDent * 0.30;
    p.z -= uDent * dentProfile * 1.35;

    p *= 1.0 + uPull * 0.36;
    p.z += uPull * (0.18 + radiusRatio * 0.32);

    float stageScale = mix(0.96, 1.03, smoothstep(0.0, 3.0, uState));
    p *= stageScale;

    vec4 mvPosition = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mvPosition;

    float perspective = uPointScale / max(-mvPosition.z, 0.2);
    float sizePulse = 1.0 + uAudio * 1.25;
    gl_PointSize = ${CONFIG.pointSize.toFixed(3)} * perspective * sizePulse * mix(1.05, 0.88, radiusRatio);

    float colorT = fract(aSeed + uTime * mix(0.034, 0.012, calm) + uProgress * 0.04);
    vColor = palette(colorT, uMode);
    vColor *= 0.72 + 0.58 * (1.0 - radiusRatio) + uAudio * 0.42;

    // 两端略微消散，让条带更像星云。
    float ribbonEdgeAlpha = mix(1.0, 0.52 + 0.48 * edgeTaper, morph);
    vAlpha = mix(0.78, 0.96, 1.0 - radiusRatio)
      * (0.82 + uAudio * 0.18)
      * ribbonEdgeAlpha;
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
    uTwist: { value: 0 },
    uRibbonTwist: { value: 0 },
    uRibbonMorph: { value: 0 },
    uRibbonHalfWidth: { value: 4 },
    uEnergy: { value: 0.5 },
    uPointScale: { value: 320 },
    uProgress: { value: 0 },
    uState: { value: 0 },
    uScatter: { value: 0 },
    uAggregate: { value: 0 },
    uDent: { value: 0 },
    uPull: { value: 0 },
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
  let currentState = 'idle'
  let visualTime = 0
  let globalRotation = 0
  let previewRotationTarget = 0
  let previewRotationSmoothed = 0
  let ribbonTwistMemory = 0
  let ribbonMorph = 0
  let ribbonTarget = 0
  let audioTarget = 0
  let modeTarget = 0.5
  let energyTarget = 0.5
  let stateTarget = 0
  let progressTarget = 0
  let twistTarget = 0
  let twistSmoothed = 0
  let twistPersistent = false
  let lastTwistInputAt = 0
  let scatterTarget = 0
  let aggregateTarget = 0
  let dentTarget = 0
  let pullTarget = 0

  function resize() {
    const width = Math.max(1, container.clientWidth)
    const height = Math.max(1, container.clientHeight)
    camera.aspect = width / height
    camera.updateProjectionMatrix()
    renderer.setSize(width, height, false)

    // 根据相机视野计算条带长度：无论 16:9、21:9，都铺到约 94% 画布宽度。
    const verticalVisible = 2 * Math.tan(THREE.MathUtils.degToRad(CONFIG.cameraFov * 0.5)) * CONFIG.cameraZ
    const horizontalVisible = verticalVisible * camera.aspect
    uniforms.uRibbonHalfWidth.value = horizontalVisible * CONFIG.ribbonViewportFill * 0.5
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

    // 截图版交互保持球形，只用转腕改变整体旋转与扭曲。
    if (Math.abs(twistTarget) > 0.01) ribbonTarget = 0
  }

  function setEnergy(value) {
    if (frozen) return
    energyTarget = clamp01(Number(value) || 0)
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

      // 选择模式：滑块只驱动完整万花筒整体旋转，不改变粒子形状。
      const previewBlend = 1 - Math.exp(-CONFIG.previewRotationResponse * delta)
      const previewTarget = currentState === 'mode' ? previewRotationTarget : 0
      previewRotationSmoothed += (previewTarget - previewRotationSmoothed) * previewBlend
      globalRotation -= previewRotationSmoothed * CONFIG.previewRotationSpeed * delta

      // 雕刻模式：戒指转腕才会展开横向条带并继续整体旋转、扭曲。
      const twistBlend = 1 - Math.exp(-CONFIG.twistResponse * delta)
      twistSmoothed += (twistTarget - twistSmoothed) * twistBlend
      if (currentState === 'sculpt') {
        globalRotation -= twistSmoothed * CONFIG.maxRotationSpeed * delta
      }
      if (Math.abs(globalRotation) > Math.PI * 8) globalRotation %= Math.PI * 2

      // 扭曲是累计雕刻结果；停手后保留，反向转腕可反向拧回。
      if (currentState === 'sculpt') {
        ribbonTwistMemory += twistSmoothed * CONFIG.ribbonTwistSpeed * delta
      }
      ribbonTwistMemory = Math.min(Math.PI * 3.2, Math.max(-Math.PI * 3.2, ribbonTwistMemory))

      const morphBlend = 1 - Math.exp(-CONFIG.ribbonMorphResponse * delta)
      ribbonMorph += (ribbonTarget - ribbonMorph) * morphBlend

      uniforms.uTime.value = visualTime
      uniforms.uAudio.value += (audioTarget - uniforms.uAudio.value) * (1 - Math.exp(-11 * delta))
      uniforms.uMode.value += (modeTarget - uniforms.uMode.value) * (1 - Math.exp(-5.2 * delta))
      uniforms.uTwist.value = twistSmoothed
      uniforms.uRibbonTwist.value = ribbonTwistMemory
      uniforms.uRibbonMorph.value = ribbonMorph
      uniforms.uEnergy.value += (energyTarget - uniforms.uEnergy.value) * (1 - Math.exp(-6.5 * delta))
      uniforms.uState.value += (stateTarget - uniforms.uState.value) * (1 - Math.exp(-5.2 * delta))
      uniforms.uProgress.value += (progressTarget - uniforms.uProgress.value) * (1 - Math.exp(-9 * delta))
      uniforms.uScatter.value += (scatterTarget - uniforms.uScatter.value) * (1 - Math.exp(-4.8 * delta))
      uniforms.uAggregate.value += (aggregateTarget - uniforms.uAggregate.value) * (1 - Math.exp(-5.2 * delta))
      uniforms.uDent.value += (dentTarget - uniforms.uDent.value) * (1 - Math.exp(-5.4 * delta))
      uniforms.uPull.value += (pullTarget - uniforms.uPull.value) * (1 - Math.exp(-4.6 * delta))
    }

    points.rotation.z = globalRotation
    points.rotation.x = (uniforms.uEnergy.value - 0.5) * 0.06 * (1 - ribbonMorph)
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

      // 离开选择模式后，预览旋转平滑停止。
      if (currentState !== 'mode') previewRotationTarget = 0
      // 离开雕刻模式后，不继续消费残留转腕速度。
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

    // -1 = 向左旋转，0 = 停止，1 = 向右旋转。
    // 只在 mode 状态生效，因此不会把万花筒展开成条带。
    setPreviewRotation,

    setTwist,

    setEnergy,

    setShape(shape = 'ball') {
      if (frozen || currentState !== 'sculpt') return
      scatterTarget = shape === 'burst' ? 1 : 0
      aggregateTarget = shape === 'aggregate' ? 1 : 0
      dentTarget = shape === 'dent' ? 1 : 0
      pullTarget = shape === 'pull' ? 1 : 0
      ribbonTarget = 0
    },

    // 鼠标左右拖动模拟转腕；纵向移动只保留原来的声音能量映射。
    setInteraction(x, y) {
      if (currentState !== 'sculpt') return
      setTwist(x, true)
      setEnergy((1 - clampSigned(Number(y) || 0)) * 0.5)
    },

    setProgress(value) {
      if (frozen) return
      progressTarget = clamp01(Number(value) || 0)
    },

    burst() {
      if (frozen || currentState !== 'sculpt') return
      scatterTarget = 1
      aggregateTarget = 0
      dentTarget = 0
      pullTarget = 0
      ribbonTarget = 0
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
        uniforms.uTwist.value = 0
        lastTwistInputAt = performance.now()
        clock.getDelta()
      }
    },

    reset() {
      frozen = false
      currentState = 'idle'
      visualTime = 0
      globalRotation = 0
      previewRotationTarget = 0
      previewRotationSmoothed = 0
      ribbonTwistMemory = 0
      ribbonMorph = 0
      ribbonTarget = 0
      audioTarget = 0
      energyTarget = 0.5
      progressTarget = 0
      twistTarget = 0
      twistSmoothed = 0
      twistPersistent = false
      lastTwistInputAt = performance.now()
      scatterTarget = 0
      aggregateTarget = 0
      dentTarget = 0
      pullTarget = 0
      uniforms.uTime.value = 0
      uniforms.uAudio.value = 0
      uniforms.uTwist.value = 0
      uniforms.uRibbonTwist.value = 0
      uniforms.uRibbonMorph.value = 0
      uniforms.uEnergy.value = 0.5
      uniforms.uProgress.value = 0
      uniforms.uScatter.value = 0
      uniforms.uAggregate.value = 0
      uniforms.uDent.value = 0
      uniforms.uPull.value = 0
      points.rotation.set(0, 0, 0)
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
