import * as THREE from 'three'

/* =========================================================
   SoundClay 简单粒子万花筒
   基于 THREE.Points + BufferGeometry

   调节重点：
   SIDES：万花筒对称轴数量
   BASE_PARTICLES：每个基础扇区的粒子数量
   MAX_RADIUS：图案半径
   POINT_SIZE：粒子大小
   ========================================================= */

const CONFIG = {
  sides: 10,
  baseParticles: 95,
  maxRadius: 2.35,
  pointSize: 0.075,

  desktopScale: 0.92,
  tabletScale: 0.82,
  mobileScale: 0.72,
}

function getResponsiveScale(width) {
  if (width <= 640) {
    return CONFIG.mobileScale
  }

  if (width <= 1100) {
    return CONFIG.tabletScale
  }

  return CONFIG.desktopScale
}

/**
 * 创建圆形发光粒子贴图。
 */
function createParticleTexture() {
  const size = 128
  const canvas = document.createElement('canvas')

  canvas.width = size
  canvas.height = size

  const context = canvas.getContext('2d')

  if (!context) {
    throw new Error('无法创建粒子 Canvas 纹理')
  }

  const gradient = context.createRadialGradient(
    size / 2,
    size / 2,
    0,
    size / 2,
    size / 2,
    size / 2,
  )

  gradient.addColorStop(0, 'rgba(255, 255, 255, 1)')
  gradient.addColorStop(0.18, 'rgba(255, 255, 255, 0.95)')
  gradient.addColorStop(0.45, 'rgba(255, 255, 255, 0.42)')
  gradient.addColorStop(1, 'rgba(255, 255, 255, 0)')

  context.fillStyle = gradient
  context.fillRect(0, 0, size, size)

  const texture = new THREE.CanvasTexture(canvas)

  texture.colorSpace = THREE.SRGBColorSpace
  texture.needsUpdate = true

  return texture
}

/**
 * 让数字稳定地生成伪随机结果。
 * 避免每次页面刷新图案完全不同。
 */
function seededRandom(seed) {
  const value = Math.sin(seed * 12.9898 + 78.233) * 43758.5453

  return value - Math.floor(value)
}

/**
 * 创建万花筒粒子数据。
 *
 * 先在一个小扇区里生成基础粒子，
 * 再把每个粒子镜像复制到所有对称轴。
 */
function createKaleidoscopeData() {
  const copiesPerParticle = CONFIG.sides * 2
  const totalParticles =
    CONFIG.baseParticles * copiesPerParticle

  const positions = new Float32Array(totalParticles * 3)
  const colors = new Float32Array(totalParticles * 3)

  const baseRadii = new Float32Array(totalParticles)
  const baseAngles = new Float32Array(totalParticles)
  const baseDepths = new Float32Array(totalParticles)
  const phases = new Float32Array(totalParticles)
  const hueOffsets = new Float32Array(totalParticles)
  const sizeFactors = new Float32Array(totalParticles)

  const sectorAngle = (Math.PI * 2) / CONFIG.sides
  const halfSector = sectorAngle / 2

  let particleIndex = 0

  for (
    let baseIndex = 0;
    baseIndex < CONFIG.baseParticles;
    baseIndex += 1
  ) {
    /*
     * sqrt 让中心不会聚集太多粒子，
     * 整体分布更均匀。
     */
    const radiusRandom = seededRandom(baseIndex + 1)
    const radius =
      0.16 +
      Math.sqrt(radiusRandom) *
        (CONFIG.maxRadius - 0.16)

    const localAngle =
      seededRandom(baseIndex + 200) * halfSector

    const depth =
      (seededRandom(baseIndex + 400) - 0.5) * 0.55

    const phase =
      seededRandom(baseIndex + 600) * Math.PI * 2

    const baseHue = seededRandom(baseIndex + 800)

    const sizeFactor =
      0.72 + seededRandom(baseIndex + 1000) * 0.7

    for (
      let sector = 0;
      sector < CONFIG.sides;
      sector += 1
    ) {
      const sectorCenter = sector * sectorAngle

      for (let mirror = 0; mirror < 2; mirror += 1) {
        const mirroredAngle =
          sectorCenter +
          (mirror === 0 ? localAngle : -localAngle)

        const arrayIndex = particleIndex * 3

        positions[arrayIndex] =
          Math.cos(mirroredAngle) * radius

        positions[arrayIndex + 1] =
          Math.sin(mirroredAngle) * radius

        positions[arrayIndex + 2] = depth

        /*
         * 初始颜色。
         * 动画中还会持续更新。
         */
        const color = new THREE.Color()

        color.setHSL(
          (baseHue + sector / CONFIG.sides) % 1,
          0.92,
          0.62,
        )

        colors[arrayIndex] = color.r
        colors[arrayIndex + 1] = color.g
        colors[arrayIndex + 2] = color.b

        baseRadii[particleIndex] = radius
        baseAngles[particleIndex] = mirroredAngle
        baseDepths[particleIndex] = depth
        phases[particleIndex] = phase
        hueOffsets[particleIndex] =
          (baseHue + sector / CONFIG.sides) % 1
        sizeFactors[particleIndex] = sizeFactor

        particleIndex += 1
      }
    }
  }

  return {
    totalParticles,
    positions,
    colors,
    baseRadii,
    baseAngles,
    baseDepths,
    phases,
    hueOffsets,
    sizeFactors,
  }
}

/**
 * 初始化粒子万花筒。
 *
 * @param {HTMLElement} container
 * @param {'express' | 'soothe'} mode
 * @returns {() => void}
 */
export function initSculpture(
  container,
  mode = 'express',
) {
  if (!(container instanceof HTMLElement)) {
    console.error('SoundClay：没有找到有效的 3D 容器')
    return () => {}
  }

  const isExpress = mode === 'express'

  const scene = new THREE.Scene()

  const camera = new THREE.PerspectiveCamera(
    36,
    Math.max(container.clientWidth, 1) /
      Math.max(container.clientHeight, 1),
    0.1,
    100,
  )

  camera.position.set(0, 0, 6.8)
  camera.lookAt(0, 0, 0)

  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: 'high-performance',
  })

  renderer.setPixelRatio(
    Math.min(window.devicePixelRatio || 1, 2),
  )

  renderer.setClearColor(0x000000, 0)

  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = isExpress ? 1.35 : 1.05

  container.replaceChildren(renderer.domElement)

  const kaleidoscopeGroup = new THREE.Group()

  kaleidoscopeGroup.position.set(0, 0, 0)

  scene.add(kaleidoscopeGroup)

  const particleData = createKaleidoscopeData()

  const geometry = new THREE.BufferGeometry()

  const positionAttribute =
    new THREE.BufferAttribute(
      particleData.positions,
      3,
    )

  const colorAttribute =
    new THREE.BufferAttribute(
      particleData.colors,
      3,
    )

  /*
   * 每一帧都会修改位置和颜色。
   */
  positionAttribute.setUsage(
    THREE.DynamicDrawUsage,
  )

  colorAttribute.setUsage(
    THREE.DynamicDrawUsage,
  )

  geometry.setAttribute(
    'position',
    positionAttribute,
  )

  geometry.setAttribute(
    'color',
    colorAttribute,
  )

  /*
   * 避免动态粒子因为包围盒变化被错误裁切。
   */
  geometry.boundingSphere = new THREE.Sphere(
    new THREE.Vector3(0, 0, 0),
    CONFIG.maxRadius * 2,
  )

  const particleTexture = createParticleTexture()

  const material = new THREE.PointsMaterial({
    size: CONFIG.pointSize,
    map: particleTexture,
    vertexColors: true,
    transparent: true,
    opacity: isExpress ? 0.96 : 0.82,
    alphaTest: 0.015,
    depthWrite: false,
    sizeAttenuation: true,
    blending: THREE.AdditiveBlending,
  })

  const particles = new THREE.Points(
    geometry,
    material,
  )

  kaleidoscopeGroup.add(particles)

  /*
   * 中心光点。
   */
  const centerMaterial = new THREE.SpriteMaterial({
    map: particleTexture,
    color: isExpress ? 0xffffff : 0xc9c3ff,
    transparent: true,
    opacity: isExpress ? 0.9 : 0.65,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  })

  const centerGlow = new THREE.Sprite(
    centerMaterial,
  )

  centerGlow.scale.set(0.75, 0.75, 1)

  kaleidoscopeGroup.add(centerGlow)

  /*
   * 第二层柔光，用来增加万花筒中心深度。
   */
  const softGlowMaterial =
    new THREE.SpriteMaterial({
      map: particleTexture,
      color: isExpress ? 0xff4f50 : 0x8d82ff,
      transparent: true,
      opacity: isExpress ? 0.25 : 0.2,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })

  const softGlow = new THREE.Sprite(
    softGlowMaterial,
  )

  softGlow.scale.set(1.7, 1.7, 1)
  softGlow.position.z = -0.3

  kaleidoscopeGroup.add(softGlow)

  const clock = new THREE.Clock()

  const workingColor = new THREE.Color()

  let animationFrame = 0

  let pointerTargetX = 0
  let pointerTargetY = 0

  let pointerX = 0
  let pointerY = 0

  let hueTarget = 0
  let hueShift = 0

  let burstTarget = 0
  let burst = 0

  let gestureEnergyTarget = 0.35
  let gestureEnergy = 0.35

  function getScale() {
    return getResponsiveScale(
      Math.max(container.clientWidth, 1),
    )
  }

  function handlePointerMove(event) {
    const rect = container.getBoundingClientRect()

    if (!rect.width || !rect.height) {
      return
    }

    const normalizedX =
      ((event.clientX - rect.left) /
        rect.width) *
        2 -
      1

    const normalizedY =
      ((event.clientY - rect.top) /
        rect.height) *
        2 -
      1

    /*
     * 左右移动：扭曲万花筒。
     * 上下移动：改变颜色。
     */
    pointerTargetY = normalizedX * 0.38
    pointerTargetX = normalizedY * 0.16
    hueTarget = normalizedY * 0.15
    gestureEnergyTarget =
      0.35 + Math.abs(normalizedX) * 0.65
  }

  function handlePointerLeave() {
    pointerTargetX = 0
    pointerTargetY = 0
    hueTarget = 0
    gestureEnergyTarget = 0.35
  }

  function handlePointerDown() {
    /*
     * 点击触发粒子爆散。
     */
    burstTarget = 1
  }

  /**
   * 后续戒指接入时，可发送这个自定义事件：
   *
   * window.dispatchEvent(
   *   new CustomEvent('soundclay:gesture', {
   *     detail: {
   *       type: 'swipe',
   *       strength: 1,
   *     },
   *   }),
   * )
   */
  function handleGesture(event) {
    const detail = event.detail ?? {}
    const type = detail.type ?? 'rotate'

    const strength = THREE.MathUtils.clamp(
      Number(detail.strength ?? 1),
      0,
      1.5,
    )

    switch (type) {
      case 'rotate':
        pointerTargetY += 0.25 * strength
        hueTarget += 0.08 * strength
        gestureEnergyTarget = 0.7 * strength
        break

      case 'swipe':
        burstTarget = Math.max(
          burstTarget,
          strength,
        )
        hueTarget += 0.18
        break

      case 'tap':
        burstTarget = Math.max(
          burstTarget,
          0.45 * strength,
        )
        hueTarget += 0.06
        break

      case 'hold':
        gestureEnergyTarget = 0.12
        hueTarget -= 0.08
        break

      default:
        break
    }
  }

  function resize() {
    const width = Math.max(
      container.clientWidth,
      1,
    )

    const height = Math.max(
      container.clientHeight,
      1,
    )

    camera.aspect = width / height
    camera.updateProjectionMatrix()

    renderer.setSize(
      width,
      height,
      false,
    )

    kaleidoscopeGroup.scale.setScalar(
      getScale(),
    )
  }

  container.addEventListener(
    'pointermove',
    handlePointerMove,
  )

  container.addEventListener(
    'pointerleave',
    handlePointerLeave,
  )

  container.addEventListener(
    'pointerdown',
    handlePointerDown,
  )

  window.addEventListener(
    'soundclay:gesture',
    handleGesture,
  )

  const resizeObserver = new ResizeObserver(
    resize,
  )

  resizeObserver.observe(container)

  resize()

  function animate() {
    const elapsed = clock.getElapsedTime()

    pointerX +=
      (pointerTargetX - pointerX) * 0.045

    pointerY +=
      (pointerTargetY - pointerY) * 0.045

    hueShift +=
      (hueTarget - hueShift) * 0.025

    gestureEnergy +=
      (gestureEnergyTarget - gestureEnergy) *
      0.045

    burst +=
      (burstTarget - burst) * 0.18

    burstTarget *= 0.88

    const positionArray =
      positionAttribute.array

    const colorArray =
      colorAttribute.array

    const slowRotation =
      elapsed * (isExpress ? 0.1 : 0.045)

    for (
      let index = 0;
      index < particleData.totalParticles;
      index += 1
    ) {
      const radius =
        particleData.baseRadii[index]

      const phase =
        particleData.phases[index]

      const radiusRatio =
        radius / CONFIG.maxRadius

      /*
       * 保持所有镜像副本同步变化，
       * 所以万花筒对称不会被破坏。
       */
      const breathing =
        1 +
        Math.sin(
          elapsed *
            (isExpress ? 1.55 : 0.85) +
            phase,
        ) *
          (isExpress ? 0.065 : 0.035)

      const burstOffset =
        burst *
        radiusRatio *
        (0.45 + Math.sin(phase) * 0.14)

      const animatedRadius =
        radius * breathing + burstOffset

      /*
       * 越靠外围，扭曲程度越明显。
       */
      const twist =
        pointerY * radiusRatio +
        Math.sin(
          elapsed * 0.42 +
            radius * 2.4,
        ) *
          0.035 *
          gestureEnergy

      const angle =
        particleData.baseAngles[index] +
        slowRotation +
        twist

      const arrayIndex = index * 3

      positionArray[arrayIndex] =
        Math.cos(angle) * animatedRadius

      positionArray[arrayIndex + 1] =
        Math.sin(angle) * animatedRadius

      positionArray[arrayIndex + 2] =
        particleData.baseDepths[index] +
        Math.sin(
          elapsed * 0.75 + phase,
        ) *
          0.11

      /*
       * 张扬模式：高饱和彩色循环。
       * 舒缓模式：降低饱和度和变化速度。
       */
      const hue =
        (
          particleData.hueOffsets[index] +
          elapsed * (isExpress ? 0.035 : 0.012) +
          hueShift +
          burst * 0.08
        ) % 1

      const saturation = isExpress
        ? 0.92
        : 0.62

      const lightness =
        (isExpress ? 0.56 : 0.64) +
        Math.sin(
          elapsed * 1.2 + phase,
        ) *
          0.12 +
        burst * 0.12

      workingColor.setHSL(
        hue < 0 ? hue + 1 : hue,
        saturation,
        THREE.MathUtils.clamp(
          lightness,
          0.35,
          0.92,
        ),
      )

      colorArray[arrayIndex] = workingColor.r
      colorArray[arrayIndex + 1] =
        workingColor.g
      colorArray[arrayIndex + 2] =
        workingColor.b
    }

    positionAttribute.needsUpdate = true
    colorAttribute.needsUpdate = true

    /*
     * 整体跟随鼠标轻微倾斜。
     */
    kaleidoscopeGroup.rotation.x =
      pointerX +
      Math.sin(elapsed * 0.24) * 0.025

    kaleidoscopeGroup.rotation.z =
      Math.sin(elapsed * 0.17) * 0.02

    const scale =
      getScale() *
      (
        1 +
        Math.sin(elapsed * 1.1) *
          (isExpress ? 0.018 : 0.01) +
        burst * 0.05
      )

    kaleidoscopeGroup.scale.setScalar(scale)

    centerGlow.rotation.z = -elapsed * 0.2

    centerGlow.scale.setScalar(
      0.72 +
        Math.sin(elapsed * 2.2) * 0.08 +
        burst * 0.3,
    )

    softGlow.scale.setScalar(
      1.65 +
        Math.sin(elapsed * 1.3) * 0.12 +
        burst * 0.5,
    )

    softGlowMaterial.opacity =
      (isExpress ? 0.23 : 0.16) +
      burst * 0.18

    renderer.render(scene, camera)

    animationFrame =
      requestAnimationFrame(animate)
  }

  animate()

  return () => {
    cancelAnimationFrame(animationFrame)

    resizeObserver.disconnect()

    container.removeEventListener(
      'pointermove',
      handlePointerMove,
    )

    container.removeEventListener(
      'pointerleave',
      handlePointerLeave,
    )

    container.removeEventListener(
      'pointerdown',
      handlePointerDown,
    )

    window.removeEventListener(
      'soundclay:gesture',
      handleGesture,
    )

    geometry.dispose()
    material.dispose()

    centerMaterial.dispose()
    softGlowMaterial.dispose()

    particleTexture.dispose()
    renderer.dispose()

    if (
      renderer.domElement.parentElement ===
      container
    ) {
      renderer.domElement.remove()
    }
  }
}