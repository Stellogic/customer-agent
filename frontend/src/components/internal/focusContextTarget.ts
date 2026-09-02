// 入口只定位已挂载的授权内容，不查找其他页面或请求额外数据。
export function focusContextTarget(target: HTMLElement | null) {
  target?.focus({ preventScroll: true });
  target?.scrollIntoView({ block: "center" });
}
