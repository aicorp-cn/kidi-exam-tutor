import { useState, useEffect } from 'react'
import { useApp } from '../store'
import { generateFingerprint } from '../fingerprint'

const PROVINCES = [
  '', '北京', '上海', '天津', '重庆',
  '广东', '浙江', '江苏', '四川', '湖北', '湖南',
  '山东', '福建', '安徽', '江西', '河南',
  '河北', '山西', '陕西', '甘肃', '青海',
  '云南', '贵州', '海南', '辽宁', '吉林', '黑龙江',
  '广西', '内蒙古', '宁夏', '新疆', '西藏',
  '台湾', '香港', '澳门',
]

const PROV_CODE = {
  '北京':'BJ','上海':'SH','天津':'TJ','重庆':'CQ',
   '广东':'GD','浙江':'ZJ','江苏':'JS','四川':'SC','湖北':'HB','湖南':'HN',
  '山东':'SD','福建':'FJ','安徽':'AH','江西':'JX','河南':'HA',
  '河北':'HE','山西':'SX','陕西':'SN','甘肃':'GS','青海':'QH',
  '云南':'YN','贵州':'GZ','海南':'HI','辽宁':'LN','吉林':'JL','黑龙江':'HL',
  '广西':'GX','内蒙古':'NM','宁夏':'NX','新疆':'XJ','西藏':'XZ',
  '台湾':'TW','香港':'HK','澳门':'MO',
}

const CITY_MAP = {
  '北京':['北京'],'上海':['上海'],'天津':['天津'],'重庆':['重庆'],
  '广东':['深圳','广州','东莞','佛山','珠海','惠州','中山','汕头'],
  '浙江':['杭州','宁波','温州','嘉兴','湖州','绍兴','金华'],
  '江苏':['南京','苏州','无锡','常州','南通','徐州','扬州'],
  '四川':['成都','绵阳','德阳','宜宾','南充'],
  '湖北':['武汉','宜昌','襄阳','荆州','黄石'],
  '湖南':['长沙','株洲','湘潭','衡阳','岳阳'],
  '山东':['济南','青岛','烟台','潍坊','临沂','淄博'],
  '福建':['福州','厦门','泉州','漳州','莆田'],
  '安徽':['合肥','芜湖','蚌埠','马鞍山','安庆'],
  '江西':['南昌','九江','赣州','景德镇'],
  '河南':['郑州','洛阳','开封','南阳','新乡'],
  '辽宁':['沈阳','大连','鞍山','抚顺'],
  '吉林':['长春','吉林','四平'],
  '黑龙江':['哈尔滨','齐齐哈尔','大庆'],
  '陕西':['西安','咸阳','宝鸡'],
  '甘肃':['兰州','天水'],
  '云南':['昆明','大理','丽江'],
  '贵州':['贵阳','遵义'],
  '海南':['海口','三亚'],
  '广西':['南宁','桂林','柳州'],
  '内蒙古':['呼和浩特','包头'],
  '新疆':['乌鲁木齐'],
  '西藏':['拉萨'],
  '台湾':['台北','高雄','台中'],
  '香港':['香港'],
  '澳门':['澳门'],
}

export function LoginScreen() {
  const { config, setAuth, goHome, logoutMessage, setLogoutMessage, storedUser, forgetUser } = useApp()

  // ── Returning user mode ──
  // showRegistration: local override — user tapped "重新注册" but hasn't committed yet.
  // storedUser is NOT cleared until a new registration succeeds, so accidental taps
  // can be undone by tapping "← 返回".
  const [showRegistration, setShowRegistration] = useState(false)
  const isReturning = !!storedUser && !showRegistration

  // ── New user form state ──
  const [province, setProvince] = useState('')
  const [city, setCity] = useState('')
  const [cities, setCities] = useState([])
  const [gender, setGender] = useState('保密')
  const [inputId, setInputId] = useState('')
  const [name, setName] = useState('')
  const [editingLocation, setEditingLocation] = useState(false)

  // ── Common state ──
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [checking, setChecking] = useState(true)
  const [mustSetPassword, setMustSetPassword] = useState(false)

  // Clear logout message after display
  useEffect(() => {
    if (logoutMessage) {
      const t = setTimeout(() => setLogoutMessage(''), 3000)
      return () => clearTimeout(t)
    }
  }, [logoutMessage])

  // Auto-detect location on mount (new users only)
  useEffect(() => {
    if (isReturning) { setChecking(false); return }
    fetch(config.apiBase + '/api/location')
      .then(r => r.json())
      .then(data => {
        const pv = PROVINCES.find(p => PROV_CODE[p] === data.province)
        if (pv) {
          setProvince(pv)
          setCities(CITY_MAP[pv] || [])
          if (data.city && CITY_MAP[pv]?.includes(data.city)) {
            setCity(data.city)
          }
        }
        if (pv && data.city && CITY_MAP[pv]?.includes(data.city)) {
          setEditingLocation(false)
        }
      })
      .catch(() => {})
      .finally(() => setChecking(false))
  }, [])

  const handleProvince = (pv) => {
    setProvince(pv)
    setCity('')
    setCities(CITY_MAP[pv] || [])
  }

  // ── Submit: returning user ──
  const submitReturning = async (e) => {
    e.preventDefault()
    if (mustSetPassword && (!password || password.length < 6)) {
      setError('请设置密码（至少6位），用于换设备登录验证'); return
    }
    setLoading(true); setError('')
    try {
      const fingerprint = await generateFingerprint()
      const r = await fetch(config.apiBase + '/auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          student_id: storedUser.student_id,
          name: storedUser.name,
          password,
          known_device: true,
          fingerprint,
        }),
      })
      const data = await r.json()
      if (!r.ok) {
        if (data.require_password) { setMustSetPassword(true); setError(data.detail); return }
        setError(data.detail || '登录失败')
        return
      }
      localStorage.setItem('exam_tutor_token', data.access_token)
      if (!data.device_token) data.device_token = crypto.randomUUID()
      setAuth(data.access_token, data)
      goHome()
    } catch { setError('网络错误，请重试') }
    finally { setLoading(false) }
  }

  // ── Submit: new user ──
  const submitNew = async (e) => {
    e.preventDefault()
    if (!inputId || !name) { setError('学号和姓名不能为空'); return }
    if (mustSetPassword && (!password || password.length < 6)) {
      setError('请设置密码（至少6位），用于换设备登录验证'); return
    }
    setLoading(true); setError('')
    try {
      const fingerprint = await generateFingerprint()
      const r = await fetch(config.apiBase + '/auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          province: PROV_CODE[province] || '',
          city, gender, input_id: inputId, name, password,
          known_device: !!storedUser,
          fingerprint,
        }),
      })
      const data = await r.json()
      if (!r.ok) {
        if (data.require_password) { setMustSetPassword(true); setError(data.detail); return }
        setError(data.detail || '登录失败')
        return
      }
      forgetUser()  // clear old storedUser before writing new one
      localStorage.setItem('exam_tutor_token', data.access_token)
      if (!data.device_token) data.device_token = crypto.randomUUID()
      setAuth(data.access_token, data)
      goHome()
    } catch { setError('网络错误，请重试') }
    finally { setLoading(false) }
  }

  if (checking) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-exam-text-muted text-sm">加载中…</div>
      </div>
    )
  }

  // ══════════════════════════════════════════
  // RETURNING USER VIEW
  // ══════════════════════════════════════════
  if (isReturning) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center px-6 pb-20">
        <div className="w-full max-w-sm">
          <h1 className="text-2xl font-bold text-center text-exam-text mb-1">
            欢迎回来
          </h1>
          <p className="text-center text-exam-text-muted text-sm mb-6">
            {storedUser.name}
          </p>

          {logoutMessage && (
            <div className="mb-4 p-3 bg-exam-accent/10 border border-exam-accent/20 rounded-lg text-center">
              <p className="text-sm text-exam-accent">{logoutMessage}</p>
            </div>
          )}

          <form onSubmit={submitReturning} className="space-y-4">
            {/* Student ID — read-only */}
            <div className="bg-exam-surface border border-exam-border rounded-lg px-3.5 py-2.5">
              <p className="text-xs text-exam-text-muted mb-0.5">学号</p>
              <p className="text-sm text-exam-text font-mono">{storedUser.student_id}</p>
            </div>

            {/* Password — only if user has one */}
            {storedUser.has_password ? (
              <input
                type="password"
                placeholder="输入密码"
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="w-full bg-exam-surface border border-exam-border rounded-lg px-3.5 py-2.5 text-sm text-exam-text placeholder:text-exam-text-muted outline-none focus:border-exam-accent"
              />
            ) : (
              <p className="text-xs text-exam-text-muted text-center">本设备已认证，无需密码</p>
            )}

            {error && <p className="text-red-400 text-sm text-center">{error}</p>}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 bg-exam-accent text-white rounded-full font-semibold active:scale-95 transition-transform disabled:opacity-50"
            >
              {loading ? '处理中…' : '登录'}
            </button>
          </form>

          <button
            onClick={() => { setShowRegistration(true); setLogoutMessage('') }}
            className="w-full mt-4 py-2 text-xs text-exam-text-muted hover:text-exam-text transition-colors"
          >
            不是{storedUser.name}？重新注册
          </button>
        </div>
      </div>
    )
  }

  // ══════════════════════════════════════════
  // NEW USER VIEW (registration)
  // ══════════════════════════════════════════
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6 pb-20">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-bold text-center text-exam-text mb-1">
          英文试卷精讲助手
        </h1>
        <p className="text-center text-exam-text-muted text-sm mb-8">
          首次使用自动注册
        </p>

        {logoutMessage && (
          <div className="mb-4 p-3 bg-exam-accent/10 border border-exam-accent/20 rounded-lg text-center">
            <p className="text-sm text-exam-accent">{logoutMessage}</p>
          </div>
        )}

        <form onSubmit={submitNew} className="space-y-4">
          {/* Location — badge when auto-detected, dropdowns when editing */}
          {!editingLocation && province && city ? (
            <div className="flex items-center justify-between bg-exam-surface border border-exam-border rounded-lg px-3.5 py-2.5">
              <span className="text-sm text-exam-text">
                {province} · {city}
              </span>
              <button
                type="button"
                onClick={() => setEditingLocation(true)}
                className="text-xs text-exam-text-muted hover:text-exam-accent transition-colors"
              >
                更正
              </button>
            </div>
          ) : (
            <div className="flex gap-2">
              <select
                value={province}
                onChange={e => handleProvince(e.target.value)}
                className="flex-1 bg-exam-surface border border-exam-border rounded-lg px-3 py-2.5 text-sm text-exam-text outline-none focus:border-exam-accent"
              >
                <option value="">省 / 直辖市</option>
                {PROVINCES.filter(Boolean).map(p => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
              <select
                value={city}
                onChange={e => setCity(e.target.value)}
                className="flex-1 bg-exam-surface border border-exam-border rounded-lg px-3 py-2.5 text-sm text-exam-text outline-none focus:border-exam-accent"
                disabled={!cities.length}
              >
                <option value="">城市</option>
                {cities.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          )}

          {/* Gender */}
          <div className="flex gap-3">
            {['男','女','保密'].map(g => (
              <label key={g} className={`flex-1 text-center py-2 rounded-lg border text-sm cursor-pointer transition-colors ${
                gender === g
                  ? 'bg-exam-accent/15 border-exam-accent text-exam-accent'
                  : 'bg-exam-surface border-exam-border text-exam-text-muted hover:text-exam-text'
              }`}>
                <input type="radio" name="gender" value={g}
                  checked={gender === g}
                  onChange={() => setGender(g)}
                  className="sr-only" />
                {g}
              </label>
            ))}
          </div>

          {/* Input ID */}
          <input
            type="text"
            placeholder="学号 / 用户名"
            value={inputId}
            onChange={e => setInputId(e.target.value)}
            className="w-full bg-exam-surface border border-exam-border rounded-lg px-3.5 py-2.5 text-sm text-exam-text placeholder:text-exam-text-muted outline-none focus:border-exam-accent"
          />

          {/* Name */}
          <input
            type="text"
            placeholder="姓名"
            value={name}
            onChange={e => setName(e.target.value)}
            className="w-full bg-exam-surface border border-exam-border rounded-lg px-3.5 py-2.5 text-sm text-exam-text placeholder:text-exam-text-muted outline-none focus:border-exam-accent"
          />

          {/* Password */}
          <input
            type="password"
            placeholder={mustSetPassword ? "请设置密码（至少6位）" : "密码（可选，换设备时需要）"}
            value={password}
            onChange={e => setPassword(e.target.value)}
            className="w-full bg-exam-surface border border-exam-border rounded-lg px-3.5 py-2.5 text-sm text-exam-text placeholder:text-exam-text-muted outline-none focus:border-exam-accent"
          />

          {error && (
            <p className="text-red-400 text-sm text-center">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 bg-exam-accent text-white rounded-full font-semibold active:scale-95 transition-transform disabled:opacity-50"
          >
            {loading ? '处理中…' : '开始使用'}
          </button>

          {/* Back to returning user — visible only when coming from "重新注册" */}
          {storedUser && (
            <button
              type="button"
              onClick={() => { setShowRegistration(false); setError('') }}
              className="w-full mt-3 py-2 text-xs text-exam-text-muted hover:text-exam-text transition-colors"
            >
              ← 返回 {storedUser.name} 的账号
            </button>
          )}
        </form>
      </div>
    </div>
  )
}
