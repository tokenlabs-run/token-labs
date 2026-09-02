            context,
            DisaggregationMode.PREFILL,
        )
        request = prepared_input.request
        multi_modal_data = prepared_input.multi_modal_data
        mm_processor_kwargs = prepared_input.mm_processor_kwargs

        # Build prompt from request (handles both prompt_embeds and token_ids)
        prompt, error = self._build_prompt_from_request(
            request,
            request_id,
            multi_modal_data,
            log_prefix="Prefill ",
            mm_processor_kwargs=mm_processor_kwargs,
        )
        if error is not None:
            # Prefill errors need disaggregated_params field
            error["disaggregated_params"] = None
            yield error
            return

        _apply_nvext_cache_salt(request, prompt)

        # Build sampling params from request using shared utility
        sampling_params = build_sampling_params(
            request,
            self.default_sampling_params,
            self.model_max_len,
            enable_rl=self.config.enable_rl,
        )

        # One protocol instance per request; carries per-request state
        # (e.g. Mooncake's transfer_id) into the response loop below.
        kv_protocol: KvConnectorProtocol = make_kv_connector_protocol(
            self.engine_client.vllm_config
        )
        _update_kv_transfer_params(
            sampling_params,
            kv_protocol.prefill_request_kv_transfer_params(),
            preserve_router_hint=True,
        )
        # Override for prefill: only generate 1 token
        sampling_params.max_tokens = 1
        sampling_params.min_tokens = 1

        # Extract LoRA request if present
        model_name = request.get("model")
        lora_request = self._resolve_lora_request(model_name)
        if lora_request:
            logger.info(
                f"Prefill request {request_id} will use LoRA adapter: {model_name} "
                f"(ID: {lora_request.lora_int_id}), path: {lora_request.lora_path}"
            )
        else:
            logger.debug(
                f"Prefill request {request_id} has no LoRA specified (model: {model_name})"
            )

        routing = request.get("routing") or {}
        dp_rank = self._to_local_dp_rank(routing.get("dp_rank"))
        priority = -int(routing.get("priority", 0))

        trace_headers = context.trace_headers()
        reasoning_ended, reasoning_parser_kwargs = _request_reasoning_metadata(request)

        async with self._abort_monitor(context, request_id, is_prefill=True):
            try:
                gen = self._generate_with_lora_admission_lock(
                    lora_request,
                    lambda admitted_lora_request: self.engine_client.generate(
                        prompt,
                        sampling_params,
                        request_id,
                        data_parallel_rank=dp_rank,
                        lora_request=admitted_lora_request,
                        trace_headers=trace_headers,
                        priority=priority,
                        **_engine_generate_reasoning_kwargs(
                            self.engine_client,
                            reasoning_ended,
                            reasoning_parser_kwargs,
                        ),
                    ),
                )
            except EngineDeadError as e:
                logger.error(f"vLLM EngineDeadError: {e}")
                logger.warning("Initiating Dynamo Runtime shutdown.")
                self.runtime.shutdown()
                os._exit(1)

            async for res in gen:
                logger.debug(f"kv transfer params: {res.kv_transfer_params}")

                token_ids = res.outputs[0].token_ids if res.outputs else []

                # For prefill worker, only one res will be generated,
                # so we can always build embedding params here without conditionals
                embedding_params = (
                    self._multimodal_request_processor.build_prefill_handoff(
                        multi_modal_data=multi_modal_data,
                        prompt_token_ids=list(res.prompt_token_ids or []),
                        mm_processor_kwargs=mm_processor_kwargs,
                    )
                )

                output: Dict[str, Any] = {
                    "token_ids": list(token_ids),
                    "disaggregated_params": self._build_disaggregated_params(
                        kv_protocol.decode_request_kv_transfer_params(res),
                        embedding_params,
                    ),
                    "completion_usage": BaseWorkerHandler._build_completion_usage(
                        request_output=res,
                    ),
                }

                # Log prefill completion with LoRA info
                self._log_with_lora_context(
                    "Prefill completed for request {request_id}{lora_info}: "
                    "generated {token_count} token(s), has_kv_params={has_kv_params}",
                    request_id,
