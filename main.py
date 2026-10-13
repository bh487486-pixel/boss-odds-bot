rict_day,
            mode_kind="picks"
        )

        _store_last_generated(chat_id, payload)

        await _send_payload(chat_id, context, payload, query=query)

    except Exception as e:
        logging.exception(f"Error en ejecutar_generacion league={league_id}: {e}")
        try:
            if query is not None:
                await query.edit_message_text(
                    f"⚠️ Ocurrió un error al generar apuestas.\n\n{e}",
                    reply_markup=main_menu_markup()
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ Ocurrió un error al generar apuestas.\n\n{e}",
                    reply_markup=main_menu_markup()
                )
        except Exception:
            pass

async def ejecutar_generacion_combo(
    chat_id,
    context,
    league_id,
    combo_kind="parlay",
    limit=6,
    query=None
):
    try:
        if query is not None:
            await query.edit_message_text("⏳ Armando combinaciones con valor...")
        else:
            await context.bot.send_message(chat_id=chat_id, text="⏳ Armando combinaciones con valor...")

        payload = _build_combo_payload(chat_id, league_id, combo_kind=combo_kind, limit=limit)

        _store_last_generated(chat_id, payload)

        await _send_payload(chat_id, context, payload, query=query)

    except Exception as e:
        logging.exception(f"Error en ejecutar_generacion_combo league={league_id} kind={combo_kind}: {e}")
        try:
            if query is not None:
                await query.edit_message_text(
                    f"⚠️ Ocurrió un error al generar combinaciones.\n\n{e}",
                    reply_markup=main_menu_markup()
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ Ocurrió un error al generar combinaciones.\n\n{e}",
                    reply_markup=main_menu_markup()
                )
        except Exception:
            pass

async def ejecutar_pick_del_dia(chat_id, context, league_id, query=None):
    try:
        cached = _get_pick_day_payload(league_id)
        if cached:
            _store_last_generated(chat_id, cached)
            await _send_payload(chat_id, context, cached, query=query)
            return

        settings = USER_SETTINGS[chat_id]
        selected, meta, _ = generar_picks(
            chat_id=chat_id,
            league_id=league_id,
            market_filter="ALL",
            max_picks=1,
            use_recent_form=settings["use_recent_form"],
            enable_runline=settings["enable_runline"],
            strict_day=True
        )

        payload = _make_payload(
            selected=selected,
            meta=meta,
            settings=settings,
            league_id=league_id,
            market_filter="ALL",
            max_picks=1,
            mode_label="Pick del Día",
            strict_day=True,
            mode_kind="picks"
        )

        _set_pick_day_payload(league_id, payload)
        _store_last_generated(chat_id, payload)

        await _send_payload(chat_id, context, payload, query=query)

    except Exception as e:
        logging.exception(f"Error en ejecutar_pick_del_dia league={league_id}: {e}")
        try:
            if query is not None:
                await query.edit_message_text(
                    f"⚠️ Ocurrió un error al generar el Pick del Día.\n\n{e}",
                    reply_markup=main_menu_markup()
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ Ocurrió un error al generar el Pick del Día.\n\n{e}",
                    reply_markup=main_menu_markup()
                )
        except Exception:
            pass

async def publish_last_to_channel(chat_id, context, indexes=None):
    payload = _get_last_generated(chat_id)
    if not payload or not payload.get("picks"):
        return False, "No hay apuestas recientes para publicar. Genera primero un Top 3, Top 6, Parlay o Combinada."

    if indexes is None:
        selected_picks = payload.get("picks", [])
    else:
        selected_picks = _subset_payload_picks(payload, indexes)

    return await _publish_picks_to_channel(chat_id, context, payload, selected_picks)

# ==========================
# MENÚS / CALLBACKS
# ==========================

# ==========================
# MENÚS / CALLBACKS
# ==========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    USER_SETTINGS[chat_id]
    await update.message.reply_text(
        _main_menu_text(chat_id),
        reply_markup=main_menu_markup()
    )



async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        data = query.data
        chat_id = query.message.chat.id
        settings = USER_SETTINGS[chat_id]

        if data == "menu:main":
            await query.answer()
            await query.edit_message_text(_main_menu_text(chat_id), reply_markup=main_menu_markup())
            return

        if data == "menu:rankings":
            await query.answer()
            await query.edit_message_text("📈 Rankings\n\nSelecciona una liga.", reply_markup=rankings_menu_markup())
            return

        if data == "menu:resultado":
            await query.answer()
            await query.edit_message_text(_build_daily_results_text(), reply_markup=daily_results_markup())
            return

        if data == "menu:games":
            await query.answer()
            await query.edit_message_text(_build_games_text(settings["league_id"]), reply_markup=league_menu_markup(settings["league_id"]))
            return

        if data == "menu:rendimiento":
            await query.answer()
            await query.edit_message_text(_build_performance_text(), reply_markup=main_menu_markup())
            return

        if data == "menu:historial":
            await query.answer()
            await query.edit_message_text(_build_history_text(), reply_markup=main_menu_markup())
            return

        if data == "menu:vip":
            await query.answer()
            await query.edit_message_text(_build_vip_text(), reply_markup=main_menu_markup())
            return

        if data == "menu:config":
            await query.answer()
            await query.edit_message_text(_config_menu_text(chat_id), reply_markup=config_menu_markup(chat_id))
            return

        if data.startswith("league:"):
            _, lid = data.split(":", 1)
            league_id = _safe_int(lid, MLB_LEAGUE_ID)
            settings["league_id"] = league_id
            await query.answer()
            await query.edit_message_text(
                f"🎯 {_league_name(league_id)}\n\nElige una opción.",
                reply_markup=league_menu_markup(league_id)
            )
            return

        if data.startswith("rankings:"):
            _, lid = data.split(":", 1)
            league_id = _safe_int(lid, MLB_LEAGUE_ID)
            await query.answer()
            await query.edit_message_text(_build_rankings_text(league_id), reply_markup=main_menu_markup())
            return

        if data.startswith("games:"):
            _, lid = data.split(":", 1)
            league_id = _safe_int(lid, settings["league_id"])
            await query.answer()
            await query.edit_message_text(
                _build_games_text(league_id),
                reply_markup=league_menu_markup(league_id)
            )
            return

        if data == "analysis:last":
            await query.answer()
            payload = _get_last_generated(chat_id) or _get_pick_day_payload(settings["league_id"])
            await query.edit_message_text(_build_analysis_text(payload), reply_markup=main_menu_markup())
            return

        if data == "config:toggle_form":
            settings["use_recent_form"] = not settings["use_recent_form"]
            await query.answer("Probabilidad inteligente actualizada")
            await query.edit_message_text(_config_menu_text(chat_id), reply_markup=config_menu_markup(chat_id))
            return

        if data == "config:toggle_runline":
            settings["enable_runline"] = not settings["enable_runline"]
            await query.answer("Run Line actualizado")
            await query.edit_message_text(_config_menu_text(chat_id), reply_markup=config_menu_markup(chat_id))
            return

        if data.startswith("config:set_filter:"):
            _, _, filter_key = data.split(":", 2)
            settings["market_filter"] = filter_key
            await query.answer("Modo por defecto actualizado")
            await query.edit_message_text(_config_menu_text(chat_id), reply_markup=config_menu_markup(chat_id))
            return

        if data.startswith("config:set_top:"):
            _, _, top_s = data.split(":", 2)
            settings["max_picks"] = _safe_int(top_s, DEFAULT_MAX_PICKS)
            await query.answer("Top por defecto actualizado")
            await query.edit_message_text(_config_menu_text(chat_id), reply_markup=config_menu_markup(chat_id))
            return

        if data.startswith("test:"):
            _, lid = data.split(":", 1)
            league_id = _safe_int(lid, LMB_LEAGUE_ID)
            await query.answer()
            await query.edit_message_text(_build_test_text(league_id), reply_markup=league_menu_markup(league_id))
            return

        if data.startswith("gen:"):
            _, lid, mode, limit_s = data.split(":", 3)
            league_id = _safe_int(lid, settings["league_id"])

            if mode == "DAY":
                await query.answer("Generando Pick del Día...", show_alert=False)
                await ejecutar_pick_del_dia(chat_id=chat_id, context=context, league_id=league_id, query=query)
                return

            if mode == "PREMIUM":
                limit = _safe_int(limit_s, 3)
                await query.answer("Generando apuestas...", show_alert=False)
                await ejecutar_generacion(
                    chat_id=chat_id,
                    context=context,
                    league_id=league_id,
                    market_filter="ALL",
                    max_picks=limit,
                    premium_mode=True,
                    query=query
                )
                return

            if mode == "ODDS":
                await query.answer("Generando apuestas...", show_alert=False)
                await ejecutar_generacion(
                    chat_id=chat_id,
                    context=context,
                    league_id=league_id,
                    market_filter="ALL",
                    max_picks=1,
                    best_odds_mode=True,
                    query=query
                )
                return

            if mode == "PARLAY":
                limit = _safe_int(limit_s, 6)
                await query.answer("Generando parlay...", show_alert=False)
                await ejecutar_generacion_combo(
                    chat_id=chat_id,
                    context=context,
                    league_id=league_id,
                    combo_kind="parlay",
                    limit=limit,
                    query=query
                )
                return

            if mode == "COMBINADA":
                limit = _safe_int(limit_s, 6)
                await query.answer("Generando combinadas...", show_alert=False)
                await ejecutar_generacion_combo(
                    chat_id=chat_id,
                    context=context,
                    league_id=league_id,
                    combo_kind="combinada",
                    limit=limit,
                    query=query
                )
                return

            if mode == "DEFAULT":
                limit = _safe_int(limit_s, settings["max_picks"])
                filter_key = settings["market_filter"]
            else:
                limit = _safe_int(limit_s, settings["max_picks"])
                filter_key = mode

            if limit <= 0:
                limit = settings["max_picks"]

            await query.answer("Generando apuestas...", show_alert=False)
            await ejecutar_generacion(
                chat_id=chat_id,
                context=context,
                league_id=league_id,
                market_filter=filter_key,
                max_picks=limit,
                query=query
            )
            return

        if data == "publish:last":
            await query.answer()
            payload = _get_last_generated(chat_id)
            if not payload or not payload.get("picks"):
                await query.edit_message_text(
                    "No hay apuestas recientes para publicar.",
                    reply_markup=main_menu_markup()
                )
                return

            await query.edit_message_text(
                _build_publish_prompt_text(payload),
                reply_markup=publish_selector_markup(payload)
            )
            return

        if data == "publish:all":
            await query.answer("Publicando todas...")
            ok, msg = await publish_last_to_channel(chat_id, context, indexes=None)
            payload = _get_last_generated(chat_id)
            if payload and payload.get("picks"):
                await query.edit_message_text(
                    _build_publish_prompt_text(payload),
                    reply_markup=publish_selector_markup(payload)
                )
            else:
                await query.edit_message_text(
                    ("✅ " + msg) if ok else ("⚠️ " + msg),
                    reply_markup=main_menu_markup()
                )
            return

        if data.startswith("publish:pick:"):
            _, _, idx_s = data.split(":", 2)
            idx = _safe_int(idx_s, -1)
            await query.answer("Publicando apuesta seleccionada...")
            ok, msg = await publish_last_to_channel(chat_id, context, indexes=[idx])
            payload = _get_last_generated(chat_id)
            if payload and payload.get("picks"):
                await query.edit_message_text(
                    _build_publish_prompt_text(payload),
                    reply_markup=publish_selector_markup(payload)
                )
            else:
                await query.edit_message_text(
                    ("✅ " + msg) if ok else ("⚠️ " + msg),
                    reply_markup=main_menu_markup()
                )
            return

        if data.startswith("resultado:"):
            if data == "resultado:publish":
                await query.answer("Publicando resultado del día...", show_alert=False)
                ok, msg = await publish_daily_results_to_channel(chat_id, context)
                payload = _build_daily_results_text()
                await query.edit_message_text(
                    payload,
                    reply_markup=daily_results_markup()
                )
                return

        if data.startswith("res:"):
            _, uid, result = data.split(":", 2)
            updated = marcar_resultado(uid, result)

            if not updated:
                await query.answer("No encontré ese pick")
                return

            current_text = query.message.text or ""
            new_text = _replace_status(current_text, _result_label(result))

            await query.edit_message_text(
                text=new_text,
                reply_markup=pick_result_markup(uid)
            )
            await query.answer(f"Marcado como {_result_label(result)}")
            return

        await query.answer()

    except Exception as e:
        logging.exception(f"Error en handle_callback: {e}")
        try:
            if update.callback_query:
                await update.callback_query.answer("Ocurrió un error")
                await update.callback_query.edit_message_text(
                    f"⚠️ Ocurrió un error.\n\n{e}",
                    reply_markup=main_menu_markup()
                )
        except Exception:
            pass

# ==========================
# ERROR HANDLER
# ==========================

# ==========================
# ERROR HANDLER
# ==========================

# ==========================
# ERROR HANDLER
# ==========================

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.exception("Error no manejado", exc_info=context.error)

# ==========================
# MAIN
# ==========================

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(on_error)

    logging.info("🤖 Boss Odds iniciado")
    app.run_polling()

if __name__ == "__main__":
    main()
