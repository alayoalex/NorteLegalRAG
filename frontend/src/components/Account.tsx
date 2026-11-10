import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { switchOrganization } from "../api";
import type { Me } from "../api";
import { apiErrorMessage } from "../messages";
import { Icon } from "./Icon";
import { MembersDialog } from "./MembersDialog";

type Props = {
  me: Me;
  onSwitched: (me: Me) => void;
  onLogout: () => void;
};

/** Organización activa, cambio de organización, miembros y cierre de sesión. */
export function Account({ me, onSwitched, onLogout }: Props) {
  const [membersOpen, setMembersOpen] = useState(false);
  const switchTo = useMutation({ mutationFn: switchOrganization, onSuccess: onSwitched });
  const { organization, organizations } = me;

  return (
    <section className="account" aria-label="Cuenta">
      {organizations.length > 1 ? (
        <label className="account-organization">
          <span className="visually-hidden">Organización</span>
          <select
            value={organization.id}
            disabled={switchTo.isPending}
            onChange={(event) => switchTo.mutate(event.target.value)}
          >
            {organizations.map((option) => (
              <option key={option.id} value={option.id}>
                {option.name}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <p className="account-organization">{organization.name}</p>
      )}
      <p className="account-email" title={me.email}>
        {me.email} · {organization.role === "owner" ? "administración" : "miembro"}
      </p>
      {switchTo.isError && (
        <p role="alert" className="error-text">
          {apiErrorMessage(switchTo.error)}
        </p>
      )}
      <div className="account-actions">
        <button type="button" className="text-button" onClick={() => setMembersOpen(true)}>
          <Icon name="users" />
          Miembros
        </button>
        <button type="button" className="text-button" onClick={onLogout}>
          <Icon name="logout" />
          Cerrar sesión
        </button>
      </div>
      {membersOpen && <MembersDialog me={me} onClose={() => setMembersOpen(false)} />}
    </section>
  );
}
