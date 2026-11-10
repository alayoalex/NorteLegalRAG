import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { login, register } from "../api";
import type { Me } from "../api";
import { apiErrorMessage } from "../messages";
import { NorthMark } from "./Icon";

type Mode = "login" | "register";

// Debe coincidir con PASSWORD_MIN_LENGTH de la API. Aquí solo adelanta el aviso.
const PASSWORD_MIN_LENGTH = 12;

type Props = {
  onSignedIn: (me: Me) => void;
  // Aviso cuando se llega aquí porque la sesión terminó, no por abrir la aplicación.
  notice: string | null;
};

export function AuthScreen({ onSignedIn, notice }: Props) {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [organization, setOrganization] = useState("");
  const submit = useMutation({
    mutationFn: () =>
      mode === "login" ? login(email, password) : register(email, password, organization),
    onSuccess: onSignedIn,
  });

  function switchMode(next: Mode) {
    setMode(next);
    submit.reset();
  }

  return (
    <main className="auth">
      <div className="auth-card">
        <div className="brand">
          <NorthMark />
          <span>NorteLegal</span>
        </div>
        <p className="auth-lead">
          Pregunta sobre los contratos y políticas de tu organización, con citas verificables.
        </p>

        <div className="auth-tabs" role="tablist" aria-label="Acceso">
          {(["login", "register"] as const).map((option) => (
            <button
              key={option}
              type="button"
              role="tab"
              aria-selected={mode === option}
              className={`auth-tab${mode === option ? " auth-tab--active" : ""}`}
              onClick={() => switchMode(option)}
            >
              {option === "login" ? "Iniciar sesión" : "Crear cuenta"}
            </button>
          ))}
        </div>

        {notice && !submit.isError && <p className="notice notice--warn">{notice}</p>}

        <form
          className="auth-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (!submit.isPending) submit.mutate();
          }}
        >
          <label className="field">
            <span>Email</span>
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label className="field">
            <span>Contraseña</span>
            <input
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
              minLength={mode === "register" ? PASSWORD_MIN_LENGTH : undefined}
              maxLength={128}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            {mode === "register" && (
              <small className="field-hint">Al menos {PASSWORD_MIN_LENGTH} caracteres.</small>
            )}
          </label>
          {mode === "register" && (
            <label className="field">
              <span>Nombre de tu organización</span>
              <input
                type="text"
                autoComplete="organization"
                required
                maxLength={120}
                value={organization}
                onChange={(event) => setOrganization(event.target.value)}
              />
              <small className="field-hint">
                Sus miembros comparten documentos. Podrás añadir a otras personas cuando se
                registren.
              </small>
            </label>
          )}

          {submit.isError && (
            <p role="alert" className="alert">
              {apiErrorMessage(submit.error)}
            </p>
          )}

          <button type="submit" className="primary-button" disabled={submit.isPending}>
            {submit.isPending
              ? "Un momento…"
              : mode === "login"
                ? "Iniciar sesión"
                : "Crear cuenta"}
          </button>
        </form>
      </div>
    </main>
  );
}
