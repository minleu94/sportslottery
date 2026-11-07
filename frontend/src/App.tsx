import React, { lazy, Suspense, useState, useEffect } from "react"
import { UIProvider } from "@/context/UIContext"
import { Navbar, type NavTab } from "@/components/Navbar"
import { WalletBanner } from "@/components/WalletBanner"
const RadarView = lazy(() => import("@/views/RadarView").then((m) => ({ default: m.RadarView })))
const ParlayView = lazy(() => import("@/views/ParlayView").then((m) => ({ default: m.ParlayView })))
const WalletView = lazy(() => import("@/views/WalletView").then((m) => ({ default: m.WalletView })))
const ProfileView = lazy(() => import("@/views/ProfileView").then((m) => ({ default: m.ProfileView })))
const ResearchView = lazy(() => import("@/views/ResearchView").then((m) => ({ default: m.ResearchView })))
import { LoginGate } from "@/components/LoginGate"
import { SidebarDrawer } from "@/components/SidebarDrawer"
import { MetricGuideModal } from "@/components/MetricGuideModal"
import { SystemHealthModal } from "@/components/SystemHealthModal"
import { StorageSettingsModal } from "@/components/StorageSettingsModal"
import { api, ApiRequestError } from "@/services/api"
import { loadRadarSnapshot } from "@/lib/radarSnapshot"
import type { Profile, WalletStatus } from "@/types"

function MainLayout() {
  const [activeTab, setActiveTab] = useState<NavTab>("radar")
  const [currentProfile, setCurrentProfile] = useState<Profile | null>(null)
  const [deepLinkMismatch, setDeepLinkMismatch] = useState(false)
  const [walletStatus, setWalletStatus] = useState<WalletStatus | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [loading, setLoading] = useState(true)

  function applyDeepLink(profile: Profile) {
    const params = new URLSearchParams(window.location.search)
    const requestedTab = params.get("tab") as NavTab | null
    const validTabs: NavTab[] = ["radar", "parlay", "wallet", "profile", "research"]
    const targetProfileId = params.get("profile_id")
    const mismatch = Boolean(targetProfileId && targetProfileId !== profile.id)
    setDeepLinkMismatch(mismatch)
    if (requestedTab && validTabs.includes(requestedTab)) setActiveTab(requestedTab)
  }

  // Drawer & Modals state
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [metricGuideOpen, setMetricGuideOpen] = useState(false)
  const [systemHealthOpen, setSystemHealthOpen] = useState(false)
  const [storageSettingsOpen, setStorageSettingsOpen] = useState(false)

  async function initApp() {
    try {
      let meRes
      try {
        meRes = await api.getAuthMe()
      } catch (authErr) {
        // A stale pre-cookie token may take precedence over a valid cookie.
        // Clear it only after a definitive 401, then retry with the HttpOnly cookie.
        if (authErr instanceof ApiRequestError && authErr.status === 401 && api.getAuthToken()) {
          api.setAuthToken(null)
          meRes = await api.getAuthMe()
        } else {
          throw authErr
        }
      }

      if (meRes.success && meRes.profile) {
        // /auth/me refreshes the HttpOnly cookie before the legacy local token is removed.
        api.setAuthToken(null)
        setCurrentProfile(meRes.profile)
        applyDeepLink(meRes.profile)
        localStorage.setItem("auth_profile_id", meRes.profile.id)
        const wRes = await api.getWalletStatus(meRes.profile.id)
        setWalletStatus(wRes)
        return
      }
    } catch (err) {
      console.error("初始化失敗:", err)
      if (err instanceof ApiRequestError && err.status === 401) {
        api.setAuthToken(null)
        localStorage.removeItem("auth_profile_id")
      }
      setCurrentProfile(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    document.title = "🐕 瘋狗運彩 (MadDog Sports) - 智慧賠率與串關風控系統 (v2.4.0)"
    const initTimer = window.setTimeout(() => void initApp(), 0)
    return () => window.clearTimeout(initTimer)
  }, [])

  async function refreshWallet(profileId: string) {
    try {
      const w = await api.getWalletStatus(profileId)
      setWalletStatus(w)
    } catch (err) {
      console.error(err)
    }
  }

  async function handleRefreshAll() {
    setRefreshing(true)
    try {
      if (currentProfile) {
        await Promise.all([
          loadRadarSnapshot(api, true),
          refreshWallet(currentProfile.id),
        ])
      }
    } catch (err) {
      console.error("更新失敗:", err)
    } finally {
      setRefreshing(false)
    }
  }

  function handleProfileChange(newProfile: Profile) {
    setCurrentProfile(newProfile)
    applyDeepLink(newProfile)
    localStorage.setItem("auth_profile_id", newProfile.id)
    refreshWallet(newProfile.id)
  }

  function handleLoginSuccess(profile: Profile) {
    setCurrentProfile(profile)
    applyDeepLink(profile)
    localStorage.setItem("auth_profile_id", profile.id)
    refreshWallet(profile.id)
  }

  async function handleLogout() {
    await api.logout()
    setCurrentProfile(null)
    setWalletStatus(null)
  }

  // If not logged in yet, render Login Gate
  if (!loading && !currentProfile) {
    return <LoginGate onLoginSuccess={handleLoginSuccess} />
  }

  return (
    <div className="min-h-screen flex flex-col font-sans selection:bg-emerald-500/30 transition-colors duration-300">
      {/* Top Navigation */}
      <Navbar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        currentProfile={currentProfile}
        onRefresh={handleRefreshAll}
        refreshing={refreshing}
        onToggleSidebar={() => setSidebarOpen(true)}
      />

      {/* Slide-out Sidebar Navigation Drawer */}
      <SidebarDrawer
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        currentProfile={currentProfile}
        wallet={walletStatus}
        onLogout={handleLogout}
        onOpenMetricGuide={() => setMetricGuideOpen(true)}
        onOpenSystemHealth={() => setSystemHealthOpen(true)}
        onOpenStorageSettings={() => setStorageSettingsOpen(true)}
        onNavigateHome={() => setActiveTab("radar")}
      />

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-3 sm:px-4 py-3 sm:py-4 space-y-3.5 relative z-10">
        {/* Wallet Risk Governance Banner (Compact single-line status ribbon on non-wallet tabs) */}
        <WalletBanner
          wallet={walletStatus}
          loading={loading}
          compact={activeTab !== "wallet"}
          onNavigateWallet={activeTab !== "wallet" ? () => setActiveTab("wallet") : undefined}
        />

        {/* Tab Views */}
        <Suspense fallback={<div className="py-12 text-center text-slate-500">頁面載入中…</div>}>
        <div className="pt-0.5">
          {deepLinkMismatch ? (
            <div role="status" className="max-w-xl mx-auto mt-8 rounded-xl border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 p-5 text-sm text-amber-900 dark:text-amber-200">
              <h2 className="font-semibold">這個 Wallet 連結屬於另一個 Profile</h2>
              <p className="mt-2 text-xs leading-5">目前登入的帳號沒有該 Profile 的 Wallet 權限。請登出後使用正確帳號登入；不會切換帳號或顯示其他玩家的帳務。</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <button onClick={() => { setDeepLinkMismatch(false); setActiveTab("profile") }} className="rounded-lg border border-amber-500/40 px-3 py-2 text-xs font-medium hover:bg-amber-100 dark:hover:bg-amber-900/40">前往個人設定</button>
                <button onClick={() => void handleLogout()} className="rounded-lg border border-slate-300 dark:border-slate-700 px-3 py-2 text-xs font-medium hover:bg-white/70 dark:hover:bg-slate-900/50">登出並使用正確帳號登入</button>
              </div>
            </div>
          ) : activeTab === "radar" && <RadarView />}
          {!deepLinkMismatch && activeTab === "parlay" && (
            <ParlayView
              wallet={walletStatus}
              onWalletUpdate={setWalletStatus}
            />
          )}
          {!deepLinkMismatch && activeTab === "wallet" && (
            <WalletView
              wallet={walletStatus}
              onWalletUpdate={setWalletStatus}
            />
          )}
          {!deepLinkMismatch && activeTab === "profile" && (
            <ProfileView
              currentProfile={currentProfile}
              onProfileChange={handleProfileChange}
            />
          )}
          {!deepLinkMismatch && activeTab === "research" && <ResearchView />}
        </div>
        </Suspense>
      </main>

      {/* System Modals */}
      <MetricGuideModal
        open={metricGuideOpen}
        onClose={() => setMetricGuideOpen(false)}
      />

      <SystemHealthModal
        open={systemHealthOpen}
        onClose={() => setSystemHealthOpen(false)}
      />

      <StorageSettingsModal
        open={storageSettingsOpen}
        onClose={() => setStorageSettingsOpen(false)}
      />

      {/* Footer */}
      <footer className="border-t border-slate-200/80 dark:border-slate-800 bg-white/50 dark:bg-slate-900/50 py-6 text-center text-xs text-slate-500 dark:text-slate-400 space-y-1 relative z-10">
        <p>🐕 台灣運彩「瘋狗流」10~500倍 高倍串關決策輔助平台 · v2.4.0</p>
        <p className="text-[11px] text-slate-400 dark:text-slate-500">
          理性投注，保護個人生活與資金。未成年人不得購買或兌領運動彩券。
        </p>
      </footer>
    </div>
  )
}

export function App() {
  return (
    <UIProvider>
      <MainLayout />
    </UIProvider>
  )
}

export default App
