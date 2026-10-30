import React, { createContext, useContext, useEffect, useState } from "react"

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

export const UIProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [theme, setThemeState] = useState<ThemeMode>(() => {
    return (localStorage.getItem("sportslottery_theme") as ThemeMode) || "system"
  })

  const [viewMode, setViewModeState] = useState<ViewMode>(() => {
    return (localStorage.getItem("sportslottery_view_mode") as ViewMode) || "cards"
  })

  const [resolvedTheme, setResolvedTheme] = useState<"dark" | "light">("dark")

  // Handle system theme matching
  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)")

    function updateResolvedTheme() {
      if (theme === "system") {
        setResolvedTheme(mediaQuery.matches ? "dark" : "light")
      } else {
        setResolvedTheme(theme)
      }
    }

    updateResolvedTheme()
    mediaQuery.addEventListener("change", updateResolvedTheme)
    return () => mediaQuery.removeEventListener("change", updateResolvedTheme)
  }, [theme])

  // Sync class on root document element
  useEffect(() => {
    const root = document.documentElement
    if (resolvedTheme === "dark") {
      root.classList.add("dark")
      root.classList.remove("light")
    } else {
      root.classList.add("light")
      root.classList.remove("dark")
    }
  }, [resolvedTheme])

  function setTheme(t: ThemeMode) {
    setThemeState(t)
    localStorage.setItem("sportslottery_theme", t)
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
