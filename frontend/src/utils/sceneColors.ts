export interface SceneColorPalette {
  background: string;
  backgroundStrong: string;
  border: string;
  text: string;
}

const SCENE_PALETTES: SceneColorPalette[] = [
  {
    background: "#eef5fc",
    backgroundStrong: "#c9dff4",
    border: "#9abfe3",
    text: "#255f96",
  },
  {
    background: "#eef8f2",
    backgroundStrong: "#cde7d8",
    border: "#9ecdb2",
    text: "#2d6b49",
  },
  {
    background: "#fff6ea",
    backgroundStrong: "#f0d9b9",
    border: "#dfc19b",
    text: "#8a5a24",
  },
  {
    background: "#f5f1fa",
    backgroundStrong: "#ded2ed",
    border: "#c5b5dc",
    text: "#655084",
  },
  {
    background: "#edf8f8",
    backgroundStrong: "#cbe7e5",
    border: "#9dcdc9",
    text: "#336f6c",
  },
  {
    background: "#fbf0f4",
    backgroundStrong: "#ebcedb",
    border: "#d9aebf",
    text: "#855065",
  },
];

const FALLBACK_PALETTE: SceneColorPalette = {
  background: "#f4f4f5",
  backgroundStrong: "#dedee1",
  border: "#b9b9bf",
  text: "#5f5f66",
};

function hashScene(scene: string): number {
  let hash = 0;

  for (let index = 0; index < scene.length; index += 1) {
    hash = (hash * 31 + scene.charCodeAt(index)) >>> 0;
  }

  return hash;
}

export function getSceneColor(scene: string): SceneColorPalette {
  const normalizedScene = scene.trim();

  if (!normalizedScene) {
    return FALLBACK_PALETTE;
  }

  if (
    normalizedScene.includes("听讲") ||
    normalizedScene.includes("讲授") ||
    normalizedScene.toLowerCase().includes("lecture")
  ) {
    return SCENE_PALETTES[0];
  }

  if (
    normalizedScene.includes("讨论") ||
    normalizedScene.includes("交流") ||
    normalizedScene.toLowerCase().includes("discussion")
  ) {
    return SCENE_PALETTES[1];
  }

  if (
    normalizedScene.includes("独立") ||
    normalizedScene.includes("自习") ||
    normalizedScene.toLowerCase().includes("independent")
  ) {
    return SCENE_PALETTES[2];
  }

  if (
    normalizedScene.includes("其他") ||
    normalizedScene.includes("未分类") ||
    normalizedScene.toLowerCase().includes("other")
  ) {
    return FALLBACK_PALETTE;
  }

  return SCENE_PALETTES[
    hashScene(normalizedScene) % SCENE_PALETTES.length
  ];
}
