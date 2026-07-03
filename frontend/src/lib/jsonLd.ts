/**
 * JSON-LD (application/ld+json) 埋め込み用のシリアライズヘルパー。
 * "<" を "<" にエスケープし、</script> による XSS/レンダリング崩れを防ぐ。
 */
export function serializeJsonLd(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
