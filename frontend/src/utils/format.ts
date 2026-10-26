export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds)) {
    return "00:00.0";
  }

  const totalTenths = Math.max(0, Math.round(seconds * 10));
  const tenths = totalTenths % 10;
  const totalWholeSeconds = Math.floor(totalTenths / 10);
  const displaySeconds = totalWholeSeconds % 60;
  const totalMinutes = Math.floor(totalWholeSeconds / 60);
  const displayMinutes = totalMinutes % 60;
  const hours = Math.floor(totalMinutes / 60);

  if (hours > 0) {
    return `${String(hours).padStart(2, "0")}:${String(
      displayMinutes
    ).padStart(2, "0")}:${String(displaySeconds).padStart(
      2,
      "0"
    )}.${tenths}`;
  }

  return `${String(displayMinutes).padStart(2, "0")}:${String(
    displaySeconds
  ).padStart(2, "0")}.${tenths}`;
}

export function formatPercent(
  value: number,
  fractionDigits = 1
): string {
  if (!Number.isFinite(value)) {
    return "—";
  }

  const normalized = Math.max(0, Math.min(1, value));

  return `${(normalized * 100).toFixed(
    Math.max(0, Math.min(3, fractionDigits))
  )}%`;
}

export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) {
    return "—";
  }

  if (bytes < 1024) {
    return `${Math.round(bytes)} B`;
  }

  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unitIndex = 0;

  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }

  const fractionDigits = value >= 100 ? 0 : value >= 10 ? 1 : 2;

  return `${value.toFixed(fractionDigits)} ${units[unitIndex]}`;
}