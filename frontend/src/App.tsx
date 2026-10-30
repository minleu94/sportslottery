import React, { useState, useEffect } from "react"
import { UIProvider } from "@/context/UIContext"
import { Navbar, type NavTab } from "@/components/Navbar"
import { WalletBanner } from "@/components/WalletBanner"
import { RadarView } from "@/views/RadarView"
import { ParlayView } from "@/views/ParlayView"
import { WalletView } from "@/views/WalletView"
import { ProfileView } from "@/views/ProfileView"
import { ResearchView } from "@/views/ResearchView"
import { LoginGate } from "@/components/LoginGate"
import { SidebarDrawer } from "@/components/SidebarDrawer"
import { MetricGuideModal } from "@/components/MetricGuideModal"
import { SystemHealthModal } from "@/components/SystemHealthModal"
import { StorageSettingsModal } from "@/components/StorageSettingsModal"
import { api } from "@/services/api"
import type { Profile, WalletStatus } from "@/types"

function MainLayout() {
  const [activeTab, setActiveTab] = useState<NavTab>("radar")
  const [currentProfile, setCurrentProfile] = useState<Profile | null>(null)
  const [walletStatus, setWalletStatus] = useState<WalletStatus | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [loading, setLoading] = useState(true)

  // Drawer & Modals state
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [metricGuideOpen, setMetricGuideOpen] = useState(false)
  const [systemHealthOpen, setSystemHealthOpen] = useState(false)
  const [storageSettingsOpen, setStorageSettingsOpen] = useState(false)

  useEffect(() => {
    initApp()
  }, [])

  async function initApp() {
    setLoading(true)
    try {
      const savedAuthId = localStorage.getItem("auth_profile_id")
      const pRes = await api.getProfiles()
      const profiles = pRes.profiles || []

      if (savedAuthId) {
        const found = profiles.find((p) => p.id === savedAuthId)
        if (found) {
          setCurrentProfile(found)
          const wRes = await api.getWalletStatus(found.id)
          setWalletStatus(wRes)
          setLoading(false)
          return
        }
      }

      // If no valid saved session, keep currentProfile null so LoginGate is rendered
      setCurrentProfile(null)
    } catch (err) {
      console.error("初始化失敗:", err)
      setCurrentProfile(null)
    } finally {
      setLoading(false)
    }
  }

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
          api.getRadar(true),
          api.getLegs(undefined, true),
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
    localStorage.setItem("auth_profile_id", newProfile.id)
    refreshWallet(newProfile.id)
  }

  function handleLoginSuccess(profile: Profile) {
    setCurrentProfile(profile)
    localStorage.setItem("auth_profile_id", profile.id)
    refreshWallet(profile.id)
  }

  function handleLogout() {
    localStorage.removeItem("auth_profile_id")
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
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-4 space-y-4 relative z-10">
        {/* Wallet Risk Governance Banner */}
        <WalletBanner wallet={walletStatus} loading={loading} />

        {/* Tab Views */}
        <div className="pt-2">
          {activeTab === "radar" && <RadarView />}
          {activeTab === "parlay" && (
            <ParlayView
              wallet={walletStatus}
              onWalletUpdate={setWalletStatus}
            />
          )}
          {activeTab === "wallet" && (
            <WalletView
              wallet={walletStatus}
              onWalletUpdate={setWalletStatus}
            />
          )}
          {activeTab === "profile" && (
            <ProfileView
              currentProfile={currentProfile}
              onProfileChange={handleProfileChange}
            />
          )}
          {activeTab === "research" && <ResearchView />}
        </div>
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
      <footer className="border-t border-slate-200 dark:border-slate-800/80 bg-white/60 dark:bg-slate-950/60 backdrop-blur py-6 text-center text-xs text-slate-500 dark:text-slate-400 space-y-1 relative z-10">
        <p>🐕 台灣運彩「瘋狗流」10~500倍 高倍串關決策輔助平台 · v2.3.0 Dev Edition</p>
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
