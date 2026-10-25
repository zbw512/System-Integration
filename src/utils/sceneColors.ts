export interface SceneColorPalette {
  background: string;
  backgroundStrong: string;
  border: string;
  text: string;
}

const SCENE_PALETTES: SceneColorPalette[] = [
  {
    background: "#e6f4ff",
    backgroundStrong: "#91caff",
    border: "#1677ff",
    text: "#0958d9",
  },
  {
    background: "#f6ffed",
    backgroundStrong: "#b7eb8f",
    border: "#52c41a",
    text: "#237804",
  },
  {
    background: "#fff7e6",
    backgroundStrong: "#ffd591",
    border: "#fa8c16",
    text: "#ad4e00",
  },
  {
    background: "#f9f0ff",
    backgroundStrong: "#d3adf7",
    border: "#722ed1",
    text: "#531dab",
  },
  {
    background: "#e6fffb",
    backgroundStrong: "#87e8de",
    border: "#13c2c2",
    text: "#006d75",
  },
  {
    background: "#fff0f6",
    backgroundStrong: "#ffadd2",
    border: "#eb2f96",
    text: "#9e1068",
  },
];

const FALLBACK_PALETTE: SceneColorPalette = {
  background: "#f5f5f5",
  backgroundStrong: "#d9d9d9",
  border: "#8c8c8c",
  text: "#595959",
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