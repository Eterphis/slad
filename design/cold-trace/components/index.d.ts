/** Cold Trace runtime (bundle.js): window.ColdTrace. The pieces are CSS classes in bundle.css. */
export type Mode = 'dark' | 'light' | 'system';

export interface CurtainOptions {
  /** Number of hairlines. Default 72. */
  count?: number;
  /** Draw the compressed reflection below a waterline instead. */
  reflect?: boolean;
  seed?: number;
}

export interface ColdTrace {
  /** Play the full press on a .ct-btn (400ms), however short the touch. Called automatically on pointerdown, Enter and Space. */
  throwKey(button: HTMLElement): void;
  /** Set and remember the colour mode; 'system' follows prefers-color-scheme. */
  setTheme(mode: Mode, root?: HTMLElement): void;
  getTheme(): Mode;
  /** Fill an element with aurora hairlines. Elements with [data-ct-curtain] are filled on load. */
  curtain(el: HTMLElement, options?: CurtainOptions): void;
  init(): void;
  version: string;
}

declare global {
  interface Window { ColdTrace: ColdTrace }
}
