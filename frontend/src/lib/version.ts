// The app version baked into the bundle at build time (Vite define).
// "dev" for local `vite build`/`vite dev` where no VITE_APP_VERSION was set.
export const APP_VERSION: string = __APP_VERSION__

/** True when this is an unreleased local build (no pinned tag baked in). */
export const IS_DEV_BUILD = APP_VERSION === "dev" || APP_VERSION === ""
