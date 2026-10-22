"use client";

import { useActionState } from "react";
import { signInWithUsername } from "@/app/actions/auth";
import { AuthSubmit } from "@/components/auth-submit";
import { USERNAME_PATTERN } from "@/lib/auth/username";

export function UsernameLoginForm() {
  const [state, action] = useActionState(signInWithUsername, { error: "" });
  return (
    <form action={action} className="username-login" aria-label="아이디 로그인">
      <div className="auth-field">
        <label htmlFor="username">아이디</label>
        <input
          id="username"
          name="username"
          type="text"
          required
          minLength={3}
          maxLength={32}
          pattern={USERNAME_PATTERN}
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          aria-describedby="username-hint"
        />
        <p id="username-hint" className="muted">
          영문자로 시작하는 3~32자, 영문·숫자·밑줄
        </p>
      </div>
      <div className="auth-field">
        <label htmlFor="password">비밀번호</label>
        <input
          id="password"
          name="password"
          type="password"
          required
          maxLength={256}
          autoComplete="current-password"
          aria-describedby={state.error ? "login-error" : undefined}
        />
      </div>
      {state.error && (
        <p id="login-error" className="error-message" role="alert">
          {state.error}
        </p>
      )}
      <AuthSubmit>로그인</AuthSubmit>
    </form>
  );
}
