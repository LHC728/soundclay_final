import * as THREE from 'three'

/**
 * SoundClay Diamond Sculpture
 *
 * 调整物体大小时，只需要修改 RESPONSIVE_SCALE。
 * 桌面端建议保持在 0.52–0.62 之间。
 */
const RESPONSIVE_SCALE = {
  desktop: 0.52,
  tablet: 0.52,
  mobile: 0.46,
}

function getResponsiveScale(width) {
  if (width <= 640) {
    return RESPONSIVE_SCALE.mobile
  }

  if (width <= 1100) {
    return RESPONSIVE_SCALE.tablet
  }

  return RESPONSIVE_SCALE.desktop
}

/**
 * 创建接近参考图的水滴形切面钻石。
 */
function createDiamondGeometry() {
  const geometry = new THREE.IcosahedronGeometry(1.42, 2)
  const position = geometry.attributes.position

  for (let index = 0; index < position.count; index += 1) {
    const x = position.getX(index)
    const y = position.getY(index)
    const z = position.getZ(index)

    /*
     * y 大致处于 -1.42 到 1.42。
     * 将它归一化到 0–1，用于控制顶部收尖和底部扩张。
     */
    const normalizedY = (y + 1.42) / 2.84

    let horizontalScale = 1

    /*
     * 顶部逐渐收尖，形成参考图中的水滴尖端。
     */
    if (normalizedY > 0.56) {
      const topProgress = (normalizedY - 0.56) / 0.44

      horizontalScale = THREE.MathUtils.lerp(
        1,
        0.12,
        topProgress,
      )
    }

    /*
     * 底部略微收紧，但保留圆润主体。
     */
    if (normalizedY < 0.18) {
      const bottomProgress = normalizedY / 0.18

      horizontalScale *= THREE.MathUtils.lerp(
        0.62,
        1,
        bottomProgress,
      )
    }

    /*
     * 中下部略微扩张，让主体不是普通锥形。
     */
    const bodyExpansion =
      1 +
      Math.sin(normalizedY * Math.PI) * 0.13

    horizontalScale *= bodyExpansion

    position.setXYZ(
      index,
      x * horizontalScale,
      y * 1.18,
      z * horizontalScale * 0.88,
    )
  }

  geometry.computeVertexNormals()
  geometry.computeBoundingSphere()

  return geometry
}

/**
 * 创建漂浮的小型切面碎片。
 */
function createShardGeometry() {
  const geometry = new THREE.TetrahedronGeometry(0.18, 0)
  geometry.computeVertexNormals()

  return geometry
}

export function initSculpture(container, mode = 'express') {
  if (!container) {
    console.warn('SoundClay: 未找到 3D 容器')
    return () => {}
  }

  const isExpress = mode === 'express'

  const scene = new THREE.Scene()

  /*
   * 相机距离增大，是钻石缩小并居中的关键。
   */
  const camera = new THREE.PerspectiveCamera(
    29,
    Math.max(container.clientWidth, 1) /
      Math.max(container.clientHeight, 1),
    0.1,
    100,
  )

  camera.position.set(0, 0.02, 7.6)
  camera.lookAt(0, 0, 0)

  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: 'high-performance',
  })

  renderer.setPixelRatio(
    Math.min(window.devicePixelRatio || 1, 2),
  )

  renderer.setSize(
    Math.max(container.clientWidth, 1),
    Math.max(container.clientHeight, 1),
    false,
  )

  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = isExpress ? 1.08 : 1

  renderer.setClearColor(0x000000, 0)

  /*
   * 避免热更新时出现多个 canvas。
   */
  container.replaceChildren(renderer.domElement)

  const sculptureGroup = new THREE.Group()

  /*
   * 整体位置固定在画布中心。
   * y 轻微下移，让尖端和底部视觉上更加平衡。
   */
  sculptureGroup.position.set(0, -0.06, 0)

  scene.add(sculptureGroup)

  const diamondGeometry = createDiamondGeometry()

  /*
   * 主体：深黑色金属与玻璃质感。
   */
  const diamondMaterial = new THREE.MeshPhysicalMaterial({
    color: isExpress ? 0x030406 : 0x171323,
    metalness: isExpress ? 0.92 : 0.55,
    roughness: isExpress ? 0.17 : 0.28,
    clearcoat: 1,
    clearcoatRoughness: 0.08,
    reflectivity: 1,
    transmission: isExpress ? 0.035 : 0.1,
    thickness: 0.65,
    flatShading: true,

    emissive: isExpress ? 0x010204 : 0x090614,
    emissiveIntensity: 0.3,
  })

  const diamond = new THREE.Mesh(
    diamondGeometry,
    diamondMaterial,
  )

  diamond.rotation.set(
    THREE.MathUtils.degToRad(-2),
    THREE.MathUtils.degToRad(10),
    THREE.MathUtils.degToRad(-3),
  )

  sculptureGroup.add(diamond)

  /*
   * 内部深色核心，提高层次。
   */
  const innerGeometry = createDiamondGeometry()

  const innerMaterial = new THREE.MeshPhysicalMaterial({
    color: isExpress ? 0x080a0f : 0x31264c,
    metalness: 0.78,
    roughness: 0.24,
    clearcoat: 0.92,
    clearcoatRoughness: 0.12,
    flatShading: true,

    emissive: isExpress ? 0x02040a : 0x10081f,
    emissiveIntensity: 0.44,
  })

  const innerDiamond = new THREE.Mesh(
    innerGeometry,
    innerMaterial,
  )

  innerDiamond.scale.setScalar(0.78)
  innerDiamond.rotation.y = -0.22

  sculptureGroup.add(innerDiamond)

  /*
   * 很淡的切面线框。
   * 不再像旧版本一样形成巨大的外部网格。
   */
  const outlineMaterial = new THREE.MeshBasicMaterial({
    color: isExpress ? 0x8190ad : 0xa896ce,
    wireframe: true,
    transparent: true,
    opacity: isExpress ? 0.075 : 0.1,
    depthWrite: false,
  })

  const outline = new THREE.Mesh(
    diamondGeometry,
    outlineMaterial,
  )

  outline.scale.setScalar(1.008)

  sculptureGroup.add(outline)

  /*
   * 前方的高亮切面。
   */
  const highlightGeometry = new THREE.TetrahedronGeometry(
    0.42,
    0,
  )

  const silverMaterial = new THREE.MeshPhysicalMaterial({
    color: 0xd9dee8,
    metalness: 0.8,
    roughness: 0.1,
    clearcoat: 1,
    clearcoatRoughness: 0.04,
    flatShading: true,
  })

  const blueMaterial = new THREE.MeshPhysicalMaterial({
    color: isExpress ? 0x819be4 : 0xa694e8,
    metalness: 0.68,
    roughness: 0.14,
    clearcoat: 1,
    flatShading: true,
  })

  const redMaterial = new THREE.MeshPhysicalMaterial({
    color: isExpress ? 0x5c0807 : 0x37626d,
    metalness: 0.58,
    roughness: 0.18,
    clearcoat: 1,
    emissive: isExpress ? 0x390000 : 0x123d42,
    emissiveIntensity: 0.48,
    flatShading: true,
  })

  const highlights = [
    {
      material: silverMaterial,
      position: [0.42, 0.32, 1.09],
      scale: [0.7, 1.9, 0.72],
      rotation: [0.24, -0.25, -0.5],
    },
    {
      material: blueMaterial,
      position: [-0.62, 0.82, 0.86],
      scale: [0.58, 1.18, 0.58],
      rotation: [0.2, 0.4, 0.7],
    },
    {
      material: redMaterial,
      position: [0.54, -0.66, 0.88],
      scale: [0.74, 1.42, 0.7],
      rotation: [0.28, -0.32, 0.52],
    },
  ]

  const highlightMeshes = highlights.map((config) => {
    const mesh = new THREE.Mesh(
      highlightGeometry,
      config.material,
    )

    mesh.position.set(...config.position)
    mesh.scale.set(...config.scale)
    mesh.rotation.set(...config.rotation)

    sculptureGroup.add(mesh)

    return mesh
  })

  /*
   * 外部碎片。
   * 半径缩小，防止画面显得过满。
   */
  const shardGeometry = createShardGeometry()

  const darkShardMaterial =
    new THREE.MeshPhysicalMaterial({
      color: 0x050608,
      metalness: 0.9,
      roughness: 0.14,
      clearcoat: 1,
      flatShading: true,
    })

  const lightShardMaterial =
    new THREE.MeshPhysicalMaterial({
      color: isExpress ? 0x9db2e9 : 0xb4a2e4,
      metalness: 0.76,
      roughness: 0.13,
      clearcoat: 1,
      flatShading: true,
    })

  const shards = []

  const shardConfigs = [
    [-1.48, 0.76, -0.15, 0.68],
    [1.5, 0.54, -0.05, 0.76],
    [-1.62, -0.46, 0.08, 0.56],
    [1.46, -0.84, 0.12, 0.62],
    [-0.96, 1.36, -0.2, 0.46],
    [0.98, -1.34, -0.12, 0.44],
    [-1.32, -1.1, -0.22, 0.38],
    [1.34, 1.12, -0.15, 0.42],
  ]

  shardConfigs.forEach((config, index) => {
    const [x, y, z, scale] = config

    const mesh = new THREE.Mesh(
      shardGeometry,
      index % 3 === 0
        ? lightShardMaterial
        : darkShardMaterial,
    )

    mesh.position.set(x, y, z)

    mesh.scale.set(
      scale * 0.66,
      scale * 1.28,
      scale * 0.72,
    )

    mesh.rotation.set(
      index * 0.33,
      index * 0.64,
      index * 0.27,
    )

    mesh.userData.baseY = y
    mesh.userData.phase = index * 0.72

    sculptureGroup.add(mesh)
    shards.push(mesh)
  })

  /*
   * 少量粒子，不形成巨大光圈。
   */
  const particleCount = 46
  const particlePositions = new Float32Array(
    particleCount * 3,
  )

  for (
    let index = 0;
    index < particleCount;
    index += 1
  ) {
    const angle = index * 2.399
    const radius = 1.7 + (index % 5) * 0.11
    const y = -1.45 + (index % 14) * 0.22

    particlePositions[index * 3] =
      Math.cos(angle) * radius

    particlePositions[index * 3 + 1] = y

    particlePositions[index * 3 + 2] =
      Math.sin(angle) * radius * 0.55
  }

  const particleGeometry = new THREE.BufferGeometry()

  particleGeometry.setAttribute(
    'position',
    new THREE.BufferAttribute(
      particlePositions,
      3,
    ),
  )

  const particleMaterial = new THREE.PointsMaterial({
    color: isExpress ? 0x8ea5dc : 0xa595db,
    size: 0.018,
    transparent: true,
    opacity: 0.38,
    depthWrite: false,
  })

  const particles = new THREE.Points(
    particleGeometry,
    particleMaterial,
  )

  sculptureGroup.add(particles)

  /*
   * 灯光。
   */
  const ambientLight = new THREE.AmbientLight(
    isExpress ? 0x525967 : 0x776a99,
    isExpress ? 0.68 : 0.88,
  )

  scene.add(ambientLight)

  const frontLight = new THREE.DirectionalLight(
    0xf7f8fc,
    isExpress ? 5.8 : 4.6,
  )

  frontLight.position.set(3.8, 4.8, 5.4)
  scene.add(frontLight)

  const leftBlueLight = new THREE.PointLight(
    isExpress ? 0x668dff : 0x9880ff,
    isExpress ? 17 : 13,
    12,
  )

  leftBlueLight.position.set(-3.6, 0.6, 3.6)
  scene.add(leftBlueLight)

  const rightRedLight = new THREE.PointLight(
    isExpress ? 0xff2a18 : 0x62ced3,
    isExpress ? 8.5 : 7,
    10,
  )

  rightRedLight.position.set(3.4, -1.4, 2.6)
  scene.add(rightRedLight)

  const bottomLight = new THREE.PointLight(
    0xffffff,
    3.8,
    9,
  )

  bottomLight.position.set(0, -3.2, 2)
  scene.add(bottomLight)

  /*
   * 动画状态。
   */
  const clock = new THREE.Clock()

  let animationFrame = 0

  let pointerTargetX = 0
  let pointerTargetY = 0

  let currentPointerX = 0
  let currentPointerY = 0

  function updateResponsiveScale() {
    const width = Math.max(
      container.clientWidth,
      1,
    )

    const scale = getResponsiveScale(width)

    sculptureGroup.scale.setScalar(scale)
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
     * 控制幅度很小，保证钻石始终留在中央。
     */
    pointerTargetY = normalizedX * 0.12
    pointerTargetX = normalizedY * 0.07
  }

  function handlePointerLeave() {
    pointerTargetX = 0
    pointerTargetY = 0
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

    updateResponsiveScale()
  }

  container.addEventListener(
    'pointermove',
    handlePointerMove,
  )

  container.addEventListener(
    'pointerleave',
    handlePointerLeave,
  )

  const resizeObserver = new ResizeObserver(resize)

  resizeObserver.observe(container)

  resize()

  function animate() {
    const elapsed = clock.getElapsedTime()

    currentPointerX +=
      (pointerTargetX - currentPointerX) *
      0.035

    currentPointerY +=
      (pointerTargetY - currentPointerY) *
      0.035

    sculptureGroup.rotation.x =
      currentPointerX +
      Math.sin(elapsed * 0.34) * 0.015

    sculptureGroup.rotation.y +=
      isExpress ? 0.00115 : 0.0008

    sculptureGroup.rotation.y +=
      (currentPointerY -
        sculptureGroup.rotation.y * 0.08) *
      0.01

    /*
     * 非常轻微的呼吸缩放。
     */
    const baseScale = getResponsiveScale(
      Math.max(container.clientWidth, 1),
    )

    const breathing =
      1 +
      Math.sin(
        elapsed *
          (isExpress ? 1.5 : 1.05),
      ) *
        (isExpress ? 0.008 : 0.015)

    sculptureGroup.scale.setScalar(
      baseScale * breathing,
    )

    innerDiamond.rotation.y =
      -elapsed * 0.055

    outline.rotation.y =
      elapsed * 0.018

    highlightMeshes.forEach(
      (mesh, index) => {
        mesh.rotation.y +=
          0.00055 + index * 0.00008
      },
    )

    shards.forEach((shard) => {
      shard.position.y =
        shard.userData.baseY +
        Math.sin(
          elapsed * 0.62 +
            shard.userData.phase,
        ) *
          0.025

      shard.rotation.y += 0.0008
    })

    particles.rotation.y =
      -elapsed * 0.018

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

    diamondGeometry.dispose()
    innerGeometry.dispose()
    highlightGeometry.dispose()
    shardGeometry.dispose()
    particleGeometry.dispose()

    diamondMaterial.dispose()
    innerMaterial.dispose()
    outlineMaterial.dispose()
    silverMaterial.dispose()
    blueMaterial.dispose()
    redMaterial.dispose()
    darkShardMaterial.dispose()
    lightShardMaterial.dispose()
    particleMaterial.dispose()

    renderer.dispose()

    if (
      renderer.domElement.parentElement ===
      container
    ) {
      renderer.domElement.remove()
    }
  }
}