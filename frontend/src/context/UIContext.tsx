import React, { createContext, useContext, useEffect, useLayoutEffect, useState } from "react"

export type ThemeMode = "dark" | "light" | "system"
export type ViewMode = "cards" | "compact"

interface UIContextType {
  theme: ThemeMode
  resolvedTheme: "dark" | "light"
  setTheme: (theme: ThemeMode) => void
  viewMode: ViewMode
  setViewMode: (mode: ViewMode) => void
  toggleViewMode: () => void
}

const UIContext = createContext<UIContextType | undefined>(undefined)

function readStoredTheme(): ThemeMode {
  try {
    const stored = localStorage.getItem("sportslottery_theme")
    return stored === "dark" || stored === "light" || stored === "system" ? stored : "system"
  } catch {
    return "system"
  }
}

function resolveTheme(theme: ThemeMode, systemPrefersDark: boolean): "dark" | "light" {
  return theme === "system" ? (systemPrefersDark ? "dark" : "light") : theme
}

export const UIProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [theme, setThemeState] = useState<ThemeMode>(readStoredTheme)

  const [viewMode, setViewModeState] = useState<ViewMode>(() => {
    return (localStorage.getItem("sportslottery_view_mode") as ViewMode) || "cards"
  })

  const [resolvedTheme, setResolvedTheme] = useState<"dark" | "light">(() => {
    return resolveTheme(theme, window.matchMedia("(prefers-color-scheme: dark)").matches)
  })

  // Handle system theme matching
  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)")

    function updateResolvedTheme() {
      setResolvedTheme(resolveTheme(theme, mediaQuery.matches))
    }

    updateResolvedTheme()
    if (theme === "system") mediaQuery.addEventListener("change", updateResolvedTheme)
    return () => mediaQuery.removeEventListener("change", updateResolvedTheme)
  }, [theme])

  // Apply before paint so a saved theme never flashes the OS theme on mobile.
  useLayoutEffect(() => {
    const root = document.documentElement
    if (resolvedTheme === "dark") {
      root.classList.add("dark")
      root.classList.remove("light")
    } else {
      root.classList.add("light")
      root.classList.remove("dark")
    }
    root.dataset.theme = resolvedTheme
  }, [resolvedTheme])

  function setTheme(t: ThemeMode) {
    setThemeState(t)
    try {
      localStorage.setItem("sportslottery_theme", t)
    } catch {
      // Theme still applies for the current session when storage is unavailable.
    }
  }

  function setViewMode(v: ViewMode) {
    setViewModeState(v)
    localStorage.setItem("sportslottery_view_mode", v)
  }

  function toggleViewMode() {
    setViewMode(viewMode === "cards" ? "compact" : "cards")
  }

  return (
    <UIContext.Provider
      value={{
        theme,
        resolvedTheme,
        setTheme,
        viewMode,
        setViewMode,
        toggleViewMode,
      }}
    >
      {children}
    </UIContext.Provider>
  )
}

export function useUI() {
  const ctx = useContext(UIContext)
  if (!ctx) throw new Error("useUI must be used within UIProvider")
  return ctx
}
