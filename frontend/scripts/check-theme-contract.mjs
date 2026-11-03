import { readdir, readFile } from "node:fs/promises"
import { join } from "node:path"
import { fileURLToPath } from "node:url"

const assetDir = fileURLToPath(new URL("../dist/assets/", import.meta.url))
const files = await readdir(assetDir)
const cssFiles = files.filter((file) => file.endsWith(".css"))

if (cssFiles.length === 0) {
  throw new Error("Theme contract failed: production CSS was not generated.")
}

const css = (await Promise.all(cssFiles.map((file) => readFile(join(assetDir, file), "utf8")))).join("\n")

// Tailwind v4 must scope `dark:` utilities to the app's root class. If this
// regresses to OS-media-query dark mode, phone and desktop can render different
// themes even when the saved in-app preference is the same.
if (!css.includes("dark\\:bg-slate-900:where(.dark,.dark *)")) {
  throw new Error("Theme contract failed: dark utilities are not scoped to the .dark root class.")
}

if (!css.includes("color-scheme:light") || !css.includes("color-scheme:dark")) {
  throw new Error("Theme contract failed: native controls must follow the active light/dark theme.")
}

console.log("Theme contract verified: app-selected theme drives dark utilities and native controls.")
