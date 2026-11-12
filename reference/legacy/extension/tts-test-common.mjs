export const VERSIONS = Object.freeze({vits: '1.0.3', onnx: '1.18.0', threads: 1, backend: 'wasm'});
export const VOICES = Object.freeze({
  ru: {id: 'ru_RU-ruslan-medium', label: 'Русский',
    short: 'Привет! Это проверка перевода на моём компьютере.',
    long: 'Сегодня мы проверяем, насколько быстро мой ноутбук создаёт русскую речь. Во время звонка перевод должен звучать понятно, без длинных пауз и без помех для камеры и микрофона.'},
  en: {id: 'en_US-joe-medium', label: 'Английский',
    short: 'Hello! This is a translation test on my computer.',
    long: 'Today we are checking how quickly this laptop can generate English speech. During a video call, the translation should sound clear, without long delays or interruptions to the camera and microphone.'}
});
export function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  if (!sorted.length) return null;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}
export function summaries(rows) {
  return Object.entries(VOICES).flatMap(([language, voice]) => ['short', 'long'].map(kind => {
    const measured = rows.filter(row => row.language === language && row.kind === kind && !row.cold && row.benchmark);
    const ratio = median(measured.map(row => row.ratio));
    return {language, voice: voice.id, kind, count: measured.length, medianRatio: ratio,
      pass: measured.length >= 5 && ratio < .5};
  }));
}
export function report(rows, downloads, environment) {
  // Whitelist report fields: never include input text, audio, tokens or URLs.
  return {schema: 1, versions: VERSIONS, environment: {
    userAgent: environment.userAgent, hardwareConcurrency: environment.hardwareConcurrency,
    deviceMemoryGB: environment.deviceMemoryGB ?? null, extensionVersion: environment.extensionVersion
  }, downloads: downloads.map(item => ({language: item.language, ms: item.ms, cached: item.cached})),
  rows: rows.map(row => Object.fromEntries(['language', 'voice', 'kind', 'cold', 'benchmark', 'prepareMs',
    'synthesisMs', 'audioSeconds', 'ratio'].map(key => [key, row[key]]))), summaries: summaries(rows)};
}
