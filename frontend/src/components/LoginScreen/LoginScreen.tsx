import { useState, type FormEvent } from 'react'
import { ArrowLeft, ArrowRight, KeyRound, LockKeyhole } from 'lucide-react'
import { login, register, type AuthSession } from '../../services/api'

interface LoginScreenProps {
  onAuthenticated: (session: AuthSession) => void;
}

// Render sign-in and one-time invited profile creation without exposing private data.
const LoginScreen = ({ onAuthenticated }: LoginScreenProps) => {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [isSubmitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  // Submit either existing credentials or one invited account registration.
  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!username.trim() || !password || isSubmitting) return
    if (mode === 'register' && password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      const session = mode === 'login'
        ? await login(username, password)
        : await register(username, password, inviteCode)
      onAuthenticated(session)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to continue.')
    } finally {
      setSubmitting(false)
    }
  }

  // Switch forms without carrying secrets or stale errors between modes.
  const switchMode = (nextMode: 'login' | 'register') => {
    setMode(nextMode)
    setPassword('')
    setConfirmPassword('')
    setInviteCode('')
    setError('')
  }

  const isRegistration = mode === 'register'
  const isDisabled = isSubmitting
    || !username.trim()
    || !password
    || (isRegistration && (!inviteCode.trim() || !confirmPassword))

  return (
    <main className="flex min-h-dvh items-center justify-center bg-[#f5f5f7] px-5 py-10 text-[#1d1d1f]">
      <section className="w-full max-w-[420px] rounded-[28px] border border-black/[0.07] bg-white p-7 shadow-[0_24px_70px_rgba(0,0,0,0.10)] sm:p-9" aria-labelledby="login-title">
        <div className="mb-8">
          <span className="anios-wordmark mb-5 flex h-12 w-12 items-center justify-center rounded-2xl text-lg font-semibold text-white">A</span>
          <p className="mb-2 text-sm font-medium text-[#0071e3]">Private intelligence</p>
          <h1 id="login-title" className="text-[34px] font-semibold tracking-[-0.04em]">
            {isRegistration ? 'Create your profile' : 'Sign in to AniOS'}
          </h1>
          <p className="mt-2 text-[15px] leading-6 text-[#6e6e73]">
            {isRegistration
              ? 'Use the one-time invitation shared with you by the AniOS owner.'
              : 'Continue to your private AniOS workspace.'}
          </p>
        </div>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <label className="block space-y-1.5">
            <span className="text-sm font-medium">Username</span>
            <input
              aria-label="Username"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={event => setUsername(event.target.value)}
              className="h-12 w-full rounded-xl border border-black/[0.14] bg-white px-3.5 text-base outline-none transition focus:border-[#0071e3] focus:ring-2 focus:ring-[#0071e3]/15"
              maxLength={50}
              pattern={'[A-Za-z0-9][A-Za-z0-9._\\-]{0,49}'}
              required
            />
          </label>
          <label className="block space-y-1.5">
            <span className="text-sm font-medium">Password</span>
            <div className="relative">
              <LockKeyhole className="pointer-events-none absolute left-3.5 top-3.5 text-[#86868b]" size={18} />
              <input
                aria-label="Password"
                autoComplete={isRegistration ? 'new-password' : 'current-password'}
                type="password"
                value={password}
                onChange={event => setPassword(event.target.value)}
                className="h-12 w-full rounded-xl border border-black/[0.14] bg-white pl-11 pr-3.5 text-base outline-none transition focus:border-[#0071e3] focus:ring-2 focus:ring-[#0071e3]/15"
                minLength={isRegistration ? 12 : 1}
                maxLength={1024}
                required
              />
            </div>
          </label>

          {isRegistration && (
            <>
              <label className="block space-y-1.5">
                <span className="text-sm font-medium">Confirm password</span>
                <div className="relative">
                  <LockKeyhole className="pointer-events-none absolute left-3.5 top-3.5 text-[#86868b]" size={18} />
                  <input
                    aria-label="Confirm password"
                    autoComplete="new-password"
                    type="password"
                    value={confirmPassword}
                    onChange={event => setConfirmPassword(event.target.value)}
                    className="h-12 w-full rounded-xl border border-black/[0.14] bg-white pl-11 pr-3.5 text-base outline-none transition focus:border-[#0071e3] focus:ring-2 focus:ring-[#0071e3]/15"
                    minLength={12}
                    maxLength={1024}
                    required
                  />
                </div>
              </label>
              <label className="block space-y-1.5">
                <span className="text-sm font-medium">Invitation code</span>
                <div className="relative">
                  <KeyRound className="pointer-events-none absolute left-3.5 top-3.5 text-[#86868b]" size={18} />
                  <input
                    aria-label="Invitation code"
                    autoComplete="off"
                    value={inviteCode}
                    onChange={event => setInviteCode(event.target.value)}
                    className="h-12 w-full rounded-xl border border-black/[0.14] bg-white pl-11 pr-3.5 text-base outline-none transition focus:border-[#0071e3] focus:ring-2 focus:ring-[#0071e3]/15"
                    minLength={16}
                    maxLength={512}
                    required
                  />
                </div>
              </label>
              <p className="text-xs leading-5 text-[#6e6e73]">
                Your username permanently owns your chats, memories, files, and agent context.
              </p>
            </>
          )}

          {error && (
            <p role="alert" className="rounded-xl bg-[#fff1f0] px-3.5 py-3 text-sm text-[#b42318]">{error}</p>
          )}

          <button
            type="submit"
            disabled={isDisabled}
            className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-[#0071e3] text-[15px] font-semibold text-white transition hover:bg-[#0077ed] disabled:cursor-not-allowed disabled:bg-[#a7c9eb]"
          >
            {isSubmitting
              ? (isRegistration ? 'Creating profile…' : 'Signing in…')
              : (isRegistration ? 'Create profile' : 'Continue')}
            {!isSubmitting && <ArrowRight size={17} />}
          </button>
          <button
            type="button"
            onClick={() => switchMode(isRegistration ? 'login' : 'register')}
            className="flex h-11 w-full items-center justify-center gap-2 rounded-xl text-sm font-medium text-[#0071e3] hover:bg-[#0071e3]/[0.06]"
          >
            {isRegistration && <ArrowLeft size={16} />}
            {isRegistration ? 'Back to sign in' : 'Create an invited profile'}
          </button>
        </form>
      </section>
    </main>
  )
}

export default LoginScreen
