import React, { useState, useEffect } from "react"
import { motion } from "framer-motion"
import { api } from "@/services/api"
import type { Profile } from "@/types"
import { Card, CardContent } from "@/components/ui/Card"
import { Button } from "@/components/ui/Button"
import { Badge } from "@/components/ui/Badge"
import { Lock, User, KeyRound, UserPlus, ShieldCheck, AlertCircle, Eye, EyeOff } from "lucide-react"

interface LoginGateProps {
  onLoginSuccess: (profile: Profile) => void
}

export const LoginGate: React.FC<LoginGateProps> = ({ onLoginSuccess }) => {
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [activeTab, setActiveTab] = useState<"login" | "register" | "pin">("login")
  
  // Login State
  const [selectedIdentifier, setSelectedIdentifier] = useState<string>("")
  const [pinCode, setPinCode] = useState<string>("")
  const [showPin, setShowPin] = useState<boolean>(false)
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  // Register State
  const [regName, setRegName] = useState<string>("")
  const [regCap, setRegCap] = useState<number>(200)
  const [regPin, setRegPin] = useState<string>("0000")
  const [regPinConfirm, setRegPinConfirm] = useState<string>("0000")

  // Change PIN State
  const [changeProfileId, setChangeProfileId] = useState<string>("")
  const [oldPin, setOldPin] = useState<string>("")
  const [newPin, setNewPin] = useState<string>("")
  const [newPinConfirm, setNewPinConfirm] = useState<string>("")

  useEffect(() => {
    loadProfiles()
  }, [])

  async function loadProfiles() {
    try {
      const res = await api.getProfiles()
      setProfiles(res.profiles || [])
      if (res.profiles && res.profiles.length > 0) {
        setSelectedIdentifier(res.profiles[0].name)
        setChangeProfileId(res.profiles[0].id)
      }
    } catch (err: any) {
      console.error(err)
    }
  }

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault()
    if (!selectedIdentifier.trim()) {
      setError("請選擇或輸入玩家名稱。")
      return
    }
    if (!pinCode.trim()) {
      setError("請輸入 4 位數 PIN 碼。")
      return
    }

    setLoading(true)
    setError(null)
    setSuccessMsg(null)
    try {
      const res = await api.loginProfile(selectedIdentifier.trim(), pinCode.trim())
      localStorage.setItem("auth_profile_id", res.profile.id)
      onLoginSuccess(res.profile)
    } catch (err: any) {
      setError(err.message || "登入失敗，請確認玩家名稱與 PIN 碼。")
    } finally {
      setLoading(false)
    }
  }

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault()
    if (!regName.trim()) {
      setError("請輸入玩家姓名。")
      return
    }
    if (regPin.length !== 4 || !/^\d{4}$/.test(regPin)) {
      setError("PIN 碼必須為 4 位純數字。")
      return
    }
    if (regPin !== regPinConfirm) {
      setError("兩次輸入的 PIN 碼不一致。")
      return
    }

    setLoading(true)
    setError(null)
    setSuccessMsg(null)
    try {
      const res = await api.registerProfile(regName.trim(), regCap, regPin)
      localStorage.setItem("auth_profile_id", res.profile.id)
      onLoginSuccess(res.profile)
    } catch (err: any) {
      setError(err.message || "註冊失敗。")
    } finally {
      setLoading(false)
    }
  }

  async function handleChangePin(e: React.FormEvent) {
    e.preventDefault()
    if (!oldPin) {
      setError("請輸入目前 PIN 碼。")
      return
    }
    if (newPin.length !== 4 || !/^\d{4}$/.test(newPin)) {
      setError("新 PIN 碼必須為 4 位純數字。")
      return
    }
    if (newPin !== newPinConfirm) {
      setError("兩次輸入的新 PIN 碼不一致。")
      return
    }

    setLoading(true)
    setError(null)
    setSuccessMsg(null)
    try {
      await api.updateProfile({
        profile_id: changeProfileId,
        current_pin: oldPin,
        new_pin: newPin,
      })
      setSuccessMsg("PIN 碼變更成功！請以此新 PIN 碼登入。")
      setOldPin("")
      setNewPin("")
      setNewPinConfirm("")
      setActiveTab("login")
    } catch (err: any) {
      setError(err.message || "變更 PIN 碼失敗。")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-gradient-to-b from-slate-900 via-slate-950 to-slate-900 text-slate-100">
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.3 }}
        className="w-full max-w-md"
      >
        {/* Hero Card */}
        <div className="text-center mb-6">
          <div className="inline-flex p-3 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 text-4xl mb-3 shadow-lg shadow-emerald-500/10">
            🐕
          </div>
          <h1 className="text-2xl font-black tracking-tight text-white flex items-center justify-center gap-2">
            台灣運彩 <span className="text-emerald-400">瘋狗流</span> 決策系統
          </h1>
          <div className="flex items-center justify-center gap-2 mt-2">
            <Badge variant="green" className="text-[10px] px-2 py-0.5 font-mono">v2.3.0 Dev</Badge>
            <span className="text-xs text-slate-400">內部成員專用登入 · 多玩家獨立娛樂資金池</span>
          </div>
        </div>

        {/* Auth Box */}
        <Card className="border-slate-800 bg-slate-900/90 shadow-2xl backdrop-blur-xl overflow-hidden">
          {/* Tabs */}
          <div className="grid grid-cols-3 border-b border-slate-800 text-center text-xs font-bold">
            <button
              onClick={() => { setActiveTab("login"); setError(null); setSuccessMsg(null) }}
              className={`py-3 transition-colors cursor-pointer flex items-center justify-center gap-1.5 ${
                activeTab === "login"
                  ? "border-b-2 border-emerald-500 text-emerald-400 bg-emerald-500/5"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <KeyRound className="w-3.5 h-3.5" />
              登入
            </button>
            <button
              onClick={() => { setActiveTab("register"); setError(null); setSuccessMsg(null) }}
              className={`py-3 transition-colors cursor-pointer flex items-center justify-center gap-1.5 ${
                activeTab === "register"
                  ? "border-b-2 border-emerald-500 text-emerald-400 bg-emerald-500/5"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <UserPlus className="w-3.5 h-3.5" />
              註冊
            </button>
            <button
              onClick={() => { setActiveTab("pin"); setError(null); setSuccessMsg(null) }}
              className={`py-3 transition-colors cursor-pointer flex items-center justify-center gap-1.5 ${
                activeTab === "pin"
                  ? "border-b-2 border-emerald-500 text-emerald-400 bg-emerald-500/5"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <ShieldCheck className="w-3.5 h-3.5" />
              變更 PIN
            </button>
          </div>

          <CardContent className="p-6">
            {error && (
              <motion.div
                initial={{ opacity: 0, y: -5 }}
                animate={{ opacity: 1, y: 0 }}
                className="mb-4 p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2"
              >
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{error}</span>
              </motion.div>
            )}

            {successMsg && (
              <motion.div
                initial={{ opacity: 0, y: -5 }}
                animate={{ opacity: 1, y: 0 }}
                className="mb-4 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs flex items-center gap-2"
              >
                <ShieldCheck className="w-4 h-4 shrink-0" />
                <span>{successMsg}</span>
              </motion.div>
            )}

            {/* TAB 1: LOGIN */}
            {activeTab === "login" && (
              <form onSubmit={handleLogin} className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5 flex items-center gap-1">
                    <User className="w-3.5 h-3.5 text-slate-400" />
                    選擇或輸入玩家名稱
                  </label>
                  {profiles.length > 0 ? (
                    <div className="space-y-2">
                      <select
                        value={selectedIdentifier}
                        onChange={(e) => setSelectedIdentifier(e.target.value)}
                        className="w-full px-3 py-2.5 rounded-lg bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500"
                      >
                        {profiles.map((p) => (
                          <option key={p.id} value={p.name}>
                            👤 {p.name} (每週上限 NT$ {p.weekly_play_cap})
                          </option>
                        ))}
                      </select>
                      <input
                        type="text"
                        placeholder="或輸入其他玩家名稱..."
                        value={selectedIdentifier}
                        onChange={(e) => setSelectedIdentifier(e.target.value)}
                        className="w-full px-3 py-2 rounded-lg bg-slate-950/60 border border-slate-800 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500"
                      />
                    </div>
                  ) : (
                    <input
                      type="text"
                      placeholder="輸入玩家名稱 (如：Archie)..."
                      value={selectedIdentifier}
                      onChange={(e) => setSelectedIdentifier(e.target.value)}
                      className="w-full px-3 py-2.5 rounded-lg bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500"
                    />
                  )}
                </div>

                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-xs font-semibold text-slate-300 flex items-center gap-1">
                      <Lock className="w-3.5 h-3.5 text-slate-400" />
                      4 位數 PIN 碼
                    </label>
                    <span className="text-[11px] text-slate-400">預設為 0000</span>
                  </div>
                  <div className="relative">
                    <input
                      type={showPin ? "text" : "password"}
                      inputMode="numeric"
                      pattern="[0-9]*"
                      maxLength={4}
                      value={pinCode}
                      onChange={(e) => setPinCode(e.target.value.replace(/\D/g, ""))}
                      placeholder="••••"
                      className="w-full px-3 py-2.5 rounded-lg bg-slate-950 border border-slate-800 text-white text-center text-lg tracking-widest font-mono focus:outline-none focus:border-emerald-500"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPin(!showPin)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
                    >
                      {showPin ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                <Button
                  type="submit"
                  disabled={loading}
                  className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white font-bold cursor-pointer"
                >
                  {loading ? "登入中..." : "🔑 登入決策台"}
                </Button>
              </form>
            )}

            {/* TAB 2: REGISTER */}
            {activeTab === "register" && (
              <form onSubmit={handleRegister} className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">玩家姓名 / 代號</label>
                  <input
                    type="text"
                    required
                    placeholder="輸入新玩家姓名..."
                    value={regName}
                    onChange={(e) => setRegName(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">每週娛樂額度上限 (NT$)</label>
                  <input
                    type="number"
                    min={50}
                    step={50}
                    value={regCap}
                    onChange={(e) => setRegCap(Number(e.target.value))}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500"
                  />
                  <p className="text-[10px] text-slate-500 mt-1">健康風控預算，預設每週 NT$ 200</p>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">設定 4 位 PIN</label>
                    <input
                      type="password"
                      inputMode="numeric"
                      pattern="[0-9]*"
                      maxLength={4}
                      value={regPin}
                      onChange={(e) => setRegPin(e.target.value.replace(/\D/g, ""))}
                      className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white text-center font-mono tracking-widest text-sm focus:outline-none focus:border-emerald-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">確認 PIN</label>
                    <input
                      type="password"
                      inputMode="numeric"
                      pattern="[0-9]*"
                      maxLength={4}
                      value={regPinConfirm}
                      onChange={(e) => setRegPinConfirm(e.target.value.replace(/\D/g, ""))}
                      className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white text-center font-mono tracking-widest text-sm focus:outline-none focus:border-emerald-500"
                    />
                  </div>
                </div>

                <Button
                  type="submit"
                  disabled={loading}
                  className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white font-bold cursor-pointer"
                >
                  {loading ? "建立中..." : "✨ 建立玩家帳號並進入"}
                </Button>
              </form>
            )}

            {/* TAB 3: CHANGE PIN */}
            {activeTab === "pin" && (
              <form onSubmit={handleChangePin} className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">選擇玩家</label>
                  <select
                    value={changeProfileId}
                    onChange={(e) => setChangeProfileId(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500"
                  >
                    {profiles.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">目前 PIN 碼</label>
                  <input
                    type="password"
                    inputMode="numeric"
                    pattern="[0-9]*"
                    maxLength={4}
                    value={oldPin}
                    onChange={(e) => setOldPin(e.target.value.replace(/\D/g, ""))}
                    placeholder="預設 0000"
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white text-center font-mono tracking-widest text-sm focus:outline-none focus:border-emerald-500"
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">新 4 位 PIN</label>
                    <input
                      type="password"
                      inputMode="numeric"
                      pattern="[0-9]*"
                      maxLength={4}
                      value={newPin}
                      onChange={(e) => setNewPin(e.target.value.replace(/\D/g, ""))}
                      className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white text-center font-mono tracking-widest text-sm focus:outline-none focus:border-emerald-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">確認新 PIN</label>
                    <input
                      type="password"
                      inputMode="numeric"
                      pattern="[0-9]*"
                      maxLength={4}
                      value={newPinConfirm}
                      onChange={(e) => setNewPinConfirm(e.target.value.replace(/\D/g, ""))}
                      className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white text-center font-mono tracking-widest text-sm focus:outline-none focus:border-emerald-500"
                    />
                  </div>
                </div>

                <Button
                  type="submit"
                  disabled={loading}
                  className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white font-bold cursor-pointer"
                >
                  {loading ? "更新中..." : "🔒 確認變更 PIN 碼"}
                </Button>
              </form>
            )}
          </CardContent>
        </Card>
      </motion.div>
    </div>
  )
}
