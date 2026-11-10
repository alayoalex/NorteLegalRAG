import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { MEMBERS_QUERY_KEY, addMember, listMembers, removeMember } from "../api";
import type { Me, Member } from "../api";
import { apiErrorMessage } from "../messages";
import { Icon } from "./Icon";

type Props = { me: Me; onClose: () => void };

/** `<dialog>` nativo: modal, con el foco atrapado y Escape para cerrar sin código propio. */
export function MembersDialog({ me, onClose }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const members = useQuery({ queryKey: MEMBERS_QUERY_KEY, queryFn: listMembers });
  const refresh = () => queryClient.invalidateQueries({ queryKey: MEMBERS_QUERY_KEY });
  const add = useMutation({
    mutationFn: addMember,
    onSuccess: () => setEmail(""),
    onSettled: refresh,
  });
  const remove = useMutation({ mutationFn: removeMember, onSettled: refresh });
  const isOwner = me.organization.role === "owner";

  useEffect(() => {
    const dialog = dialogRef.current;
    // En StrictMode el efecto se ejecuta dos veces.
    if (dialog && !dialog.open) dialog.showModal();
  }, []);

  function confirmRemove(member: Member) {
    const question = `¿Quitar a ${member.email} de ${me.organization.name}? Dejará de ver sus documentos al momento.`;
    if (window.confirm(question)) remove.mutate(member.user_id);
  }

  return (
    <dialog ref={dialogRef} className="dialog" aria-labelledby="members-title" onClose={onClose}>
      <header className="dialog-header">
        <h2 id="members-title">Miembros de {me.organization.name}</h2>
        <button
          type="button"
          className="icon-button"
          aria-label="Cerrar"
          onClick={() => dialogRef.current?.close()}
        >
          <Icon name="close" />
        </button>
      </header>
      <p className="muted">Todos los miembros ven, suben y consultan los mismos documentos.</p>

      {isOwner && (
        <form
          className="member-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (!add.isPending) add.mutate(email);
          }}
        >
          <label className="field">
            <span>Añadir por email</span>
            <input
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="persona@despacho.com"
            />
            <small className="field-hint">Esa persona debe haberse registrado antes.</small>
          </label>
          <button type="submit" className="primary-button" disabled={add.isPending}>
            Añadir
          </button>
        </form>
      )}
      {[add, remove].map(
        (mutation, index) =>
          mutation.isError && (
            <p key={index} role="alert" className="alert">
              {apiErrorMessage(mutation.error)}
            </p>
          ),
      )}

      {members.isPending && <p className="muted">Cargando…</p>}
      {members.isError && (
        <p role="alert" className="alert">
          {apiErrorMessage(members.error)}
        </p>
      )}
      {members.isSuccess && (
        <ul className="member-list">
          {members.data.map((member) => (
            <li key={member.user_id} className="member">
              <span className="member-email">
                {member.email}
                {member.user_id === me.user_id && " (tú)"}
              </span>
              <span className="muted">
                {member.role === "owner" ? "Administración" : "Miembro"}
              </span>
              {isOwner && member.role === "member" && (
                <button
                  type="button"
                  className="icon-button icon-button--danger"
                  aria-label={`Quitar a ${member.email}`}
                  title="Quitar de la organización"
                  disabled={remove.isPending}
                  onClick={() => confirmRemove(member)}
                >
                  <Icon name="trash" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </dialog>
  );
}
