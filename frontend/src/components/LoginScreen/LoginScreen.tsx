import { useState, type FormEvent } from 'react'
import { ArrowLeft, ArrowRight, LockKeyhole, Phone, UserRound } from 'lucide-react'
import { login, requestAccess, type AuthSession } from '../../services/api'
import { Logo } from '../Logo/Logo'

interface LoginScreenProps {
  onAuthenticated: (session: AuthSession) => void;
}

// Render sign-in and one-time invited profile creation without exposing private data.
const LoginScreen = ({ onAuthenticated }: LoginScreenProps) => {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [reason, setReason] = useState('')
  const [phone, setPhone] = useState('')
  const [isSubmitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  // Set once the request is in. Signing up no longer signs anyone in, so the
  // form has an outcome of its own to report.
  const [awaitingApproval, setAwaitingApproval] = useState(false)

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
      if (mode === 'login') {
        onAuthenticated(await login(username, password))
      } else {
        // Creating a profile records a request; it does not create an account.
        // The credentials entered here become the account's own when approved.
        await requestAccess(
          displayName.trim() || username,
          username,
          password,
          phone.trim(),
          reason,
        )
        setAwaitingApproval(true)
      }
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
    setDisplayName('')
    setReason('')
    setPhone('')
    setError('')
    setAwaitingApproval(false)
  }

  const isRegistration = mode === 'register'
  const isDisabled = isSubmitting
    || !username.trim()
    || !password
    || (isRegistration && !confirmPassword)
    // The number is required, but only its presence is checked here. The
    // server owns the format rule and returns a message worth reading; a
    // second copy of E.164 in the browser is one more thing to keep in step.
    || (isRegistration && !phone.trim())

  if (awaitingApproval) {
    return (
      <main className="flex min-h-dvh items-center justify-center bg-[#f5f5f7] px-5 py-10 text-[#1d1d1f]">
        <section className="w-full max-w-[420px] rounded-[28px] border border-black/[0.07] bg-white p-7 shadow-[0_24px_70px_rgba(0,0,0,0.10)] sm:p-9">
          <span className="anios-wordmark mb-5 flex h-12 w-12 items-center justify-center rounded-2xl text-white"><Logo className="h-7 w-7" title="DeepMatter" /></span>
          <h1 className="text-[28px] font-semibold tracking-[-0.03em]">Request sent</h1>
          <p className="mt-2 text-[15px] leading-6 text-[#6e6e73]">
            The owner has to approve you before your account exists. Once they do,
            sign in with the username and password you just chose — there is no
            code to wait for.
          </p>
          <button
            type="button"
            onClick={() => switchMode('login')}
            className="mt-6 flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-[#0071e3] text-[15px] font-semibold text-white transition hover:bg-[#0077ed]"
          >
            Back to sign in
          </button>
        </section>
      </main>
    )
  }

  return (
    <main className="flex min-h-dvh items-center justify-center bg-[#f5f5f7] px-5 py-10 text-[#1d1d1f]">
      <section className="w-full max-w-[420px] rounded-[28px] border border-black/[0.07] bg-white p-7 shadow-[0_24px_70px_rgba(0,0,0,0.10)] sm:p-9" aria-labelledby="login-title">
        <div className="mb-8">
          <span className="anios-wordmark mb-5 flex h-12 w-12 items-center justify-center rounded-2xl text-white"><Logo className="h-7 w-7" title="DeepMatter" /></span>
          <p className="mb-2 text-sm font-medium text-[#0071e3]">Private intelligence</p>
          <h1 id="login-title" className="text-[34px] font-semibold tracking-[-0.04em]">
            {isRegistration ? 'Create your profile' : 'Sign in to DeepMatter'}
          </h1>
          <p className="mt-2 text-[15px] leading-6 text-[#6e6e73]">
            {isRegistration
              ? 'Choose your credentials. The owner approves before the account is created.'
              : 'Continue to your private DeepMatter workspace.'}
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
                <span className="text-sm font-medium">Your name</span>
                <div className="relative">
                  <UserRound className="pointer-events-none absolute left-3.5 top-3.5 text-[#86868b]" size={18} />
                  <input
                    aria-label="Your name"
                    autoComplete="name"
                    value={displayName}
                    onChange={event => setDisplayName(event.target.value)}
                    className="h-12 w-full rounded-xl border border-black/[0.14] bg-white pl-11 pr-3.5 text-base outline-none transition focus:border-[#0071e3] focus:ring-2 focus:ring-[#0071e3]/15"
                    maxLength={80}
                    placeholder="So the owner knows who is asking"
                  />
                </div>
              </label>
              <label className="block space-y-1.5">
                <span className="text-sm font-medium">Phone number</span>
                <div className="relative">
                  <Phone className="pointer-events-none absolute left-3.5 top-3.5 text-[#86868b]" size={18} />
                  <input
                    aria-label="Phone number"
                    autoComplete="tel"
                    inputMode="tel"
                    value={phone}
                    onChange={event => setPhone(event.target.value)}
                    className="h-12 w-full rounded-xl border border-black/[0.14] bg-white pl-11 pr-3.5 text-base outline-none transition focus:border-[#0071e3] focus:ring-2 focus:ring-[#0071e3]/15"
                    maxLength={32}
                    placeholder="+1 202 555 0100"
                  />
                </div>
                <span className="block text-xs leading-5 text-[#6e6e73]">
                  Include your country code. This is the number the assistant will
                  recognise you by over iMessage once you are approved.
                </span>
              </label>
              <label className="block space-y-1.5">
                <span className="text-sm font-medium">Anything to add <span className="font-normal text-[#86868b]">(optional)</span></span>
                <textarea
                  aria-label="Anything to add"
                  value={reason}
                  onChange={event => setReason(event.target.value)}
                  className="min-h-[72px] w-full rounded-xl border border-black/[0.14] bg-white px-3.5 py-3 text-base outline-none transition focus:border-[#0071e3] focus:ring-2 focus:ring-[#0071e3]/15"
                  maxLength={500}
                />
              </label>
              <p className="text-xs leading-5 text-[#6e6e73]">
                The owner reviews every request. Nothing is created until they approve it.
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
              ? (isRegistration ? 'Sending request…' : 'Signing in…')
              : (isRegistration ? 'Request access' : 'Continue')}
            {!isSubmitting && <ArrowRight size={17} />}
          </button>
          <button
            type="button"
            onClick={() => switchMode(isRegistration ? 'login' : 'register')}
            className="flex h-11 w-full items-center justify-center gap-2 rounded-xl text-sm font-medium text-[#0071e3] hover:bg-[#0071e3]/[0.06]"
          >
            {isRegistration && <ArrowLeft size={16} />}
            {isRegistration ? 'Back to sign in' : 'Request an account'}
          </button>
        </form>
      </section>
    </main>
  )
}

export default LoginScreen
