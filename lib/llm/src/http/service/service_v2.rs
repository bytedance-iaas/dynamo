// SPDX-FileCopyrightText: Copyright (c) 2024-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

use std::sync::Arc;
use std::time::Duration;

use super::metrics;
use super::Metrics;
use super::RouteDoc;
use crate::discovery::ModelManager;
use crate::request_template::RequestTemplate;
use anyhow::Result;
use derive_builder::Builder;
use dynamo_runtime::DistributedRuntime;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;
use dynamo_runtime::transports::etcd;

/// HTTP service shared state
pub struct State {
    metrics: Arc<Metrics>,
    manager: Arc<ModelManager>,
    runtime: Option<Arc<DistributedRuntime>>,
}

impl State {
    pub fn new(manager: Arc<ModelManager>) -> Self {
        Self {
            manager,
            metrics: Arc::new(Metrics::default()),
            runtime: None,
        }
    }

    pub fn with_runtime(manager: Arc<ModelManager>, runtime: Arc<DistributedRuntime>) -> Self {
        Self {
            manager,
            metrics: Arc::new(Metrics::default()),
            runtime: Some(runtime),
        }
    }

    /// Get the Prometheus [`Metrics`] object which tracks request counts and inflight requests
    pub fn metrics_clone(&self) -> Arc<Metrics> {
        self.metrics.clone()
    }

    pub fn manager(&self) -> &ModelManager {
        Arc::as_ref(&self.manager)
    }

    pub fn manager_clone(&self) -> Arc<ModelManager> {
        self.manager.clone()
    }

    /// Get the DistributedRuntime if available
    pub fn runtime(&self) -> Option<&DistributedRuntime> {
        self.runtime.as_ref().map(|r| r.as_ref())
    }

    // TODO
    pub fn sse_keep_alive(&self) -> Option<Duration> {
        None
    }
}

#[derive(Clone)]
pub struct HttpService {
    // The state we share with every request handler
    state: Arc<State>,

    router: axum::Router,
    port: u16,
    host: String,
    route_docs: Vec<RouteDoc>,
}

#[derive(Clone, Builder)]
#[builder(pattern = "owned", build_fn(private, name = "build_internal"))]
pub struct HttpServiceConfig {
    #[builder(default = "8787")]
    port: u16,

    #[builder(setter(into), default = "String::from(\"0.0.0.0\")")]
    host: String,

    // #[builder(default)]
    // custom: Vec<axum::Router>
    #[builder(default = "true")]
    enable_chat_endpoints: bool,

    #[builder(default = "true")]
    enable_cmpl_endpoints: bool,

    #[builder(default = "true")]
    enable_embeddings_endpoints: bool,

    #[builder(default = "None")]
    request_template: Option<RequestTemplate>,

    #[builder(default = "None")]
    runtime: Option<Arc<DistributedRuntime>>,
}

impl HttpService {
    pub fn builder() -> HttpServiceConfigBuilder {
        HttpServiceConfigBuilder::default()
    }

    pub fn state_clone(&self) -> Arc<State> {
        self.state.clone()
    }

    pub fn state(&self) -> &State {
        Arc::as_ref(&self.state)
    }

    pub fn model_manager(&self) -> &ModelManager {
        self.state().manager()
    }

    pub async fn spawn(&self, cancel_token: CancellationToken) -> JoinHandle<Result<()>> {
        let this = self.clone();
        tokio::spawn(async move { this.run(cancel_token).await })
    }

    pub async fn run(&self, cancel_token: CancellationToken) -> Result<()> {
        let address = format!("{}:{}", self.host, self.port);
        tracing::info!(address, "Starting HTTP service on: {address}");

        let listener = tokio::net::TcpListener::bind(address.as_str())
            .await
            .unwrap_or_else(|_| panic!("could not bind to address: {address}"));

        let router = self.router.clone();
        let observer = cancel_token.child_token();

        axum::serve(listener, router)
            .with_graceful_shutdown(observer.cancelled_owned())
            .await
            .inspect_err(|_| cancel_token.cancel())?;

        Ok(())
    }

    /// Documentation of exposed HTTP endpoints
    pub fn route_docs(&self) -> &[RouteDoc] {
        &self.route_docs
    }
}

impl HttpServiceConfigBuilder {
    pub fn build(self, etcd_client: Option<etcd::Client>) -> Result<HttpService, anyhow::Error> {
        let config: HttpServiceConfig = self.build_internal()?;

        let model_manager = Arc::new(ModelManager::new());
        let state = if let Some(runtime) = config.runtime {
            Arc::new(State::with_runtime(model_manager, runtime))
        } else {
            Arc::new(State::new(model_manager))
        };

        // enable prometheus metrics
        let registry = metrics::Registry::new();
        state.metrics_clone().register(&registry)?;

        let mut router = axum::Router::new();

        let mut all_docs = Vec::new();

        let mut routes = vec![
            metrics::router(registry, None),
            super::openai::list_models_router(state.clone(), None),
            super::health::health_check_router(state.clone(), None),
            super::clear_kv_blocks::clear_kv_blocks_router(state.clone(), None),
        ];
        if etcd_client.is_some() {
            routes.push(super::openai::list_workers_router(
                etcd_client.unwrap(),
                state.clone(),
            ));
        }

        if config.enable_chat_endpoints {
            routes.push(super::openai::chat_completions_router(
                state.clone(),
                config.request_template,
                None,
            ));
        }

        if config.enable_cmpl_endpoints {
            routes.push(super::openai::completions_router(state.clone(), None));
        }

        if config.enable_embeddings_endpoints {
            routes.push(super::openai::embeddings_router(state.clone(), None));
        }

        // for (route_docs, route) in routes.into_iter().chain(self.routes.into_iter()) {
        //     router = router.merge(route);
        //     all_docs.extend(route_docs);
        // }

        for (route_docs, route) in routes.into_iter() {
            router = router.merge(route);
            all_docs.extend(route_docs);
        }

        Ok(HttpService {
            state,
            router,
            port: config.port,
            host: config.host,
            route_docs: all_docs,
        })
    }

    pub fn with_request_template(mut self, request_template: Option<RequestTemplate>) -> Self {
        self.request_template = Some(request_template);
        self
    }
}
