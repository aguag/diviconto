"""Dettaglio di un viaggio: spese, partecipanti e bilancio (3 tab)."""

from __future__ import annotations

from datetime import datetime

from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.list import OneLineListItem, TwoLineListItem
from kivymd.uix.screen import MDScreen

from diviconto import core
from diviconto.i18n import tr
from diviconto.money import format_money
from ui.widgets import FormTextField, toast


def _format_when(iso_ts: str) -> str:
    """Formatta un timestamp ISO (UTC) come data/ora locale leggibile."""
    try:
        return datetime.fromisoformat(iso_ts).astimezone().strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return iso_ts or ""


class TripDetailScreen(MDScreen):
    """Schermata con bottom navigation: Spese / Partecipanti / Bilancio."""

    _dialog = None

    def on_pre_enter(self, *args):
        app = MDApp.get_running_app()
        trip = app.current_trip
        if trip is None:
            self.manager.current = "trips"
            return
        self.ids.topbar.title = f"{trip.name} [{trip.base_currency}]"
        self.refresh_all()

    def on_enter(self, *args):
        # Sync automatico all'apertura del viaggio (se loggati), senza bloccare.
        app = MDApp.get_running_app()
        if app.sync.is_logged_in():
            app.run_async(app.sync.sync, lambda _: self.refresh_all(), lambda _exc: None)

    def refresh_all(self):
        self.refresh_expenses()
        self.refresh_people()
        self.refresh_balance()

    def go_back(self):
        self.manager.current = "trips"

    def do_sync(self):
        app = MDApp.get_running_app()
        if not app.sync.is_logged_in():
            toast(tr("Accedi per sincronizzare"))
            return
        toast(tr("Sincronizzazione…"))

        def done(_):
            self.refresh_all()
            toast(tr("Sincronizzato"))

        app.run_async(app.sync.sync, done, lambda exc: toast(str(exc)))

    # ---- Condivisione ----------------------------------------------------
    def show_share_code(self):
        app = MDApp.get_running_app()
        if not app.sync.is_logged_in():
            toast(tr("Accedi per condividere il viaggio"))
            return
        trip_id = app.current_trip.id
        toast(tr("Recupero codice…"))

        def done(code):
            if not code:
                toast(tr("Sincronizza prima per generare il codice"))
                return
            self._dialog = MDDialog(
                # auto_dismiss=False: si chiude solo coi pulsanti. Senza questo,
                # il rilascio del tocco che ha aperto il dialog cade fuori da esso
                # e lo chiuderebbe subito (il sync è veloce e apre a metà tocco).
                auto_dismiss=False,
                title=tr("Codice del viaggio"),
                text=tr("Condividi questo codice:\n\n[b]{code}[/b]\n\n"
                        "Gli amici lo inseriscono in \"Unisciti a un viaggio\".").format(code=code),
                buttons=[
                    MDFlatButton(text=tr("Copia"), on_release=lambda *_: self._copy_code(code)),
                    MDFlatButton(text=tr("Chiudi"), on_release=lambda *_: self._dialog.dismiss()),
                ],
            )
            self._dialog.open()

        # Prima sincronizza (così il viaggio esiste lato server), poi legge il codice.
        def work():
            app.sync.sync()
            return app.sync.share_code(trip_id)

        app.run_async(work, done, lambda exc: toast(str(exc)))

    def _copy_code(self, code: str):
        from kivy.core.clipboard import Clipboard
        Clipboard.copy(code)
        toast(tr("Codice copiato"))

    # ---- Gestione viaggio / condivisione ---------------------------------
    def _my_role(self):
        """('owner' | 'member' | 'owner'-per-default) per il viaggio corrente.

        Senza cache membri (viaggio locale non ancora condiviso) → owner: l'hai
        creato tu. Altrimenti si guarda il ruolo della propria email.
        """
        app = MDApp.get_running_app()
        members = app.db.trip_members_detail(app.current_trip.id)
        if not members:
            return "owner", []
        me = app.sync.current_user()
        mine = next((m["role"] for m in members if m["email"] == me), None)
        others = [m["email"] for m in members if m["email"] != me]
        return (mine or "member"), others

    def open_trip_menu(self):
        role, others = self._my_role()
        rows = MDBoxLayout(orientation="vertical", spacing="4dp",
                           adaptive_height=True, size_hint_y=None)
        rows.height = 0

        def add_btn(text, cb):
            b = MDRaisedButton(text=text, pos_hint={"center_x": .5})
            b.bind(on_release=lambda *_: cb())
            rows.add_widget(b)
            rows.height += 56

        if role == "owner":
            add_btn(tr("Elimina viaggio"), self._confirm_delete_trip)
            if others:
                add_btn(tr("Gestisci condivisione"), self._open_share_management)
        else:
            add_btn(tr("Abbandona viaggio"), self._confirm_leave_trip)

        self._dialog = MDDialog(
            auto_dismiss=False, title=tr("Viaggio"), type="custom", content_cls=rows,
            buttons=[MDFlatButton(text=tr("Chiudi"), on_release=lambda *_: self._dialog.dismiss())],
        )
        self._dialog.open()

    def _confirm_delete_trip(self):
        self._dialog.dismiss()
        self._confirm(tr("Eliminare il viaggio?"),
                      tr("Sparirà per tutti i partecipanti alla prossima sincronizzazione."),
                      self._do_delete_trip)

    def _do_delete_trip(self):
        app = MDApp.get_running_app()
        trip = app.current_trip
        core.delete_trip(app.db, trip.id)
        toast(tr("Viaggio eliminato"))
        self.manager.current = "trips"
        self.manager.get_screen("trips").refresh()
        if app.sync.is_logged_in():  # propaga subito, se possibile
            app.run_async(app.sync.sync, lambda _r: None, lambda _e: None)

    def _confirm_leave_trip(self):
        self._dialog.dismiss()
        app = MDApp.get_running_app()
        if not app.sync.is_logged_in():
            toast(tr("Accedi per abbandonare il viaggio"))
            return
        self._confirm(tr("Abbandonare il viaggio?"),
                      tr("Verrà rimosso da questo dispositivo; resta per gli altri."),
                      self._do_leave_trip)

    def _do_leave_trip(self):
        app = MDApp.get_running_app()
        trip_id = app.current_trip.id

        def done(_):
            toast(tr("Hai abbandonato il viaggio"))
            self.manager.current = "trips"
            self.manager.get_screen("trips").refresh()

        toast(tr("Esco dal viaggio…"))
        app.run_async(lambda: app.sync.leave_trip(trip_id), done, lambda exc: toast(str(exc)))

    def _open_share_management(self):
        self._dialog.dismiss()
        app = MDApp.get_running_app()
        _role, others = self._my_role()
        box = MDBoxLayout(orientation="vertical", spacing="6dp",
                          adaptive_height=True, size_hint_y=None)
        box.height = 0
        for email in others:
            row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height="44dp", spacing="8dp")
            row.add_widget(MDLabel(text=email, valign="center", shorten=True))
            btn = MDFlatButton(text=tr("Rimuovi"), theme_text_color="Error")
            btn.bind(on_release=lambda _w, e=email: self._do_remove_member(e))
            row.add_widget(btn)
            box.add_widget(row)
            box.height += 50
        revoke = MDRaisedButton(text=tr("Revoca a tutti + nuovo codice"), pos_hint={"center_x": .5})
        revoke.bind(on_release=lambda *_: self._confirm_revoke())
        box.add_widget(revoke)
        box.height += 56
        self._dialog = MDDialog(
            auto_dismiss=False, title=tr("Gestisci condivisione"), type="custom", content_cls=box,
            buttons=[MDFlatButton(text=tr("Chiudi"), on_release=lambda *_: self._dialog.dismiss())],
        )
        self._dialog.open()

    def _do_remove_member(self, email):
        self._dialog.dismiss()
        app = MDApp.get_running_app()
        trip_id = app.current_trip.id

        def done(_):
            toast(tr("Rimosso {email}").format(email=email))
            self.refresh_all()

        toast(tr("Rimuovo…"))
        app.run_async(lambda: app.sync.remove_member(trip_id, email), done,
                      lambda exc: toast(str(exc)))

    def _confirm_revoke(self):
        self._dialog.dismiss()
        self._confirm(tr("Revocare la condivisione a tutti?"),
                      tr("Gli altri membri vengono rimossi e il codice rigenerato "
                         "(il vecchio non funzionerà più)."),
                      self._do_revoke)

    def _do_revoke(self):
        app = MDApp.get_running_app()
        trip_id = app.current_trip.id

        def done(newcode):
            toast(tr("Condivisione revocata. Nuovo codice: {code}").format(code=newcode))
            self.refresh_all()

        toast(tr("Revoco…"))
        app.run_async(lambda: app.sync.revoke_sharing(trip_id), done,
                      lambda exc: toast(str(exc)))

    def _confirm(self, title, text, on_yes):
        self._dialog = MDDialog(
            auto_dismiss=False, title=title, text=text,
            buttons=[
                MDFlatButton(text=tr("Annulla"), on_release=lambda *_: self._dialog.dismiss()),
                MDRaisedButton(
                    text=tr("Conferma"),
                    on_release=lambda *_: (self._dialog.dismiss(), on_yes()),
                ),
            ],
        )
        self._dialog.open()

    # ---- Spese -----------------------------------------------------------
    def refresh_expenses(self):
        app = MDApp.get_running_app()
        trip = app.current_trip
        lst = self.ids.expense_list
        lst.clear_widgets()
        people = {p.id: p.name for p in app.db.list_participants(trip.id)}
        expenses = app.db.list_expenses(trip.id)
        if not expenses:
            lst.add_widget(OneLineListItem(text=tr("Nessuna spesa")))
            return
        for e in expenses:
            payer = people.get(e.payer_id, "?")
            amount = format_money(e.amount, e.currency)
            if e.currency != trip.base_currency:
                amount += f" = {format_money(e.amount_base, trip.base_currency)}"
            desc = e.description or tr("(senza descrizione)")
            item = TwoLineListItem(
                text=f"{payer}: {amount}",
                secondary_text=f"{desc} · {_format_when(e.created_at)}",
            )
            item.bind(on_release=lambda _w, exp=e: self.open_expense_actions(exp))
            lst.add_widget(item)

    def open_expense_form(self):
        app = MDApp.get_running_app()
        if not app.db.list_participants(app.current_trip.id):
            toast(tr("Aggiungi prima un partecipante"))
            return
        self.manager.current = "expense_form"

    # ---- Azioni su una spesa (modifica descrizione / cancella) ------------
    def _expense_detail_text(self, exp) -> str:
        """Testo del popup spesa: pagante, tipo divisione e quote per persona."""
        app = MDApp.get_running_app()
        trip = app.current_trip
        people = {p.id: p.name for p in app.db.list_participants(trip.id)}
        splits = app.db.list_splits(exp.id)
        mode = splits[0].mode if splits else "equal"
        mode_label = tr("Parti uguali") if mode == "equal" else tr("Importi esatti")
        lines = [
            exp.description or tr("(senza descrizione)"),
            "",
            f"[b]{tr('Pagante')}:[/b] {people.get(exp.payer_id, '?')}",
            f"[b]{tr('Tipo')}:[/b] {mode_label}",
            f"[b]{tr('Importo')}:[/b] {format_money(exp.amount, exp.currency)}",
        ]
        if exp.currency != trip.base_currency:
            lines.append(f"          (= {format_money(exp.amount_base, trip.base_currency)})")
        lines.append("")
        lines.append(f"[b]{tr('Quote')}[/b] (in {trip.base_currency}):")
        for s in splits:
            lines.append(f"  • {people.get(s.participant_id, '?')}: "
                         f"{format_money(s.share_base, trip.base_currency)}")
        return "\n".join(lines)

    def open_expense_actions(self, exp):
        self._dialog = MDDialog(
            auto_dismiss=False,
            title=tr("Spesa"),
            text=self._expense_detail_text(exp),
            buttons=[
                MDFlatButton(text=tr("Modifica descrizione"),
                             on_release=lambda *_: self._edit_description(exp)),
                MDFlatButton(text=tr("Elimina Spesa"), theme_text_color="Custom",
                             text_color=(0.8, 0, 0, 1),
                             on_release=lambda *_: self._confirm_delete(exp)),
                MDFlatButton(text=tr("Chiudi"), on_release=lambda *_: self._dialog.dismiss()),
            ],
        )
        self._dialog.open()

    def _edit_description(self, exp):
        self._dialog.dismiss()
        self._edit_field = FormTextField(text=exp.description, hint_text=tr("Descrizione"))
        self._dialog = MDDialog(
            auto_dismiss=False,
            title=tr("Modifica descrizione"),
            type="custom",
            content_cls=self._edit_field,
            buttons=[
                MDFlatButton(text=tr("Annulla"), on_release=lambda *_: self._dialog.dismiss()),
                MDRaisedButton(text=tr("Salva"), on_release=lambda *_: self._save_description(exp)),
            ],
        )
        self._dialog.open()

    def _save_description(self, exp):
        app = MDApp.get_running_app()
        try:
            core.update_expense_description(app.db, exp.id, self._edit_field.text)
        except ValueError as exc:
            toast(str(exc))
            return
        self._dialog.dismiss()
        self.refresh_expenses()
        toast(tr("Descrizione aggiornata"))

    def _confirm_delete(self, exp):
        self._dialog.dismiss()
        desc = exp.description or tr("(senza descrizione)")
        self._dialog = MDDialog(
            auto_dismiss=False,
            title=tr("Cancellare la spesa?"),
            text=f"{desc}\n" + tr("L'operazione non è annullabile."),
            buttons=[
                MDFlatButton(text=tr("Annulla"), on_release=lambda *_: self._dialog.dismiss()),
                MDRaisedButton(text=tr("Cancella"), md_bg_color=(0.8, 0, 0, 1),
                               on_release=lambda *_: self._do_delete(exp)),
            ],
        )
        self._dialog.open()

    def _do_delete(self, exp):
        app = MDApp.get_running_app()
        core.delete_expense(app.db, exp.id)
        self._dialog.dismiss()
        self.refresh_expenses()
        self.refresh_balance()
        toast(tr("Spesa cancellata"))

    # ---- Partecipanti ----------------------------------------------------
    def refresh_people(self):
        app = MDApp.get_running_app()
        trip = app.current_trip
        lst = self.ids.people_list
        lst.clear_widgets()
        people = app.db.list_participants(trip.id)
        if not people:
            lst.add_widget(OneLineListItem(text=tr("Nessun partecipante")))
            return
        for p in people:
            lst.add_widget(OneLineListItem(text=p.name))

    def add_person(self):
        app = MDApp.get_running_app()
        field = self.ids.new_person
        try:
            core.add_participant(app.db, app.current_trip.id, field.text)
        except ValueError as exc:
            toast(str(exc))
            return
        field.text = ""
        self.refresh_people()
        self.refresh_balance()

    # ---- Bilancio --------------------------------------------------------
    def refresh_balance(self):
        app = MDApp.get_running_app()
        box = self.ids.balance_box
        box.clear_widgets()
        bal = core.compute_balance(app.db, app.current_trip.id)
        cur = bal.base_currency

        box.add_widget(self._row(tr("Saldi"), bold=True))
        for name in bal.net:
            net = bal.net[name]
            stato = tr("in credito") if net > 0 else (tr("in debito") if net < 0 else tr("in pari"))
            box.add_widget(self._row(
                tr("{name}: {net} ({state})  — pagato {paid}, dovuto {owed}").format(
                    name=name, net=format_money(net, cur), state=stato,
                    paid=format_money(bal.paid[name]), owed=format_money(bal.owed[name]),
                )
            ))

        box.add_widget(self._row(""))
        if not bal.settlements:
            box.add_widget(self._row(tr("Conti già in pari."), bold=True))
            return
        box.add_widget(self._row(tr("Pagamenti suggeriti"), bold=True))
        for s in bal.settlements:
            box.add_widget(self._row(
                "  " + tr("{debtor} deve dare {amount} a {creditor}").format(
                    debtor=s.debtor, amount=format_money(s.amount, cur), creditor=s.creditor)
            ))

    @staticmethod
    def _row(text: str, bold: bool = False) -> MDLabel:
        return MDLabel(
            text=f"[b]{text}[/b]" if bold else text,
            markup=True,
            font_style="Subtitle1" if bold else "Body2",
            adaptive_height=True,
            size_hint_y=None,
            height="28dp",
        )
