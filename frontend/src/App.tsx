import React, { useState, useEffect } from "react"
import { Navbar, type NavTab } from "@/components/Navbar"
import { WalletBanner } from "@/components/WalletBanner"
import { RadarView } from "@/views/RadarView"
import { ParlayView } from "@/views/ParlayView"
import { WalletView } from "@/views/WalletView"
import { ProfileView } from "@/views/ProfileView"
import { ResearchView } from "@/views/ResearchView"
import { api } from "@/services/api"
import type { Profile, WalletStatus } from "@/types"

export function App() {
  const [activeTab, setActiveTab] = useState<NavTab>("radar")
  const [currentProfile, setCurrentProfile] = useState<Profile | null>(null)
  const [walletStatus, setWalletStatus] = useState<WalletStatus | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [loading, setLoading] = useState(true)

  // Initialize profile & wallet
  useEffect(() => {
    initApp()
  }, [])

  async function initApp() {
    setLoading(true)
    try {
      const pRes = await api.getProfiles()
      const def = pRes.profiles?.find((p) => p.id === "default") || pRes.profiles?.[0]
      if (def) {
        setCurrentProfile(def)
        const wRes = await api.getWalletStatus(def.id)
        setWalletStatus(wRes)
      }
    } catch (err) {
      console.error("初始化失敗:", err)
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
    refreshWallet(newProfile.id)
  }

  return (
    <div className="min-h-screen bg-[#0b0f19] text-slate-100 flex flex-col font-sans selection:bg-emerald-500/30">
      {/* Top Navigation */}
      <Navbar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        currentProfile={currentProfile}
        onRefresh={handleRefreshAll}
        refreshing={refreshing}
      />

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-4 space-y-4">
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

      {/* Footer */}
      <footer className="border-t border-slate-900 bg-slate-950/60 py-6 text-center text-xs text-slate-500 space-y-1">
        <p>🐕 台灣運彩「瘋狗流」10~500倍 高倍串關決策輔助平台 · v2.0 Modern Edition</p>
        <p className="text-[11px] text-slate-600">
          理性投注，保護個人生活與資金。未成年人不得購買或兌領運動彩券。
        </p>
      </footer>
    </div>
  )
}

export default App
