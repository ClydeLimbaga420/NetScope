(function (root) {
  const terminalStatuses = new Set(["done", "error", "cancelled"]);

  async function pollJob(jobId, request, interval) {
    while (true) {
      const job = await request(`/api/jobs/${encodeURIComponent(jobId)}`);
      if (terminalStatuses.has(job.status)) return job;
      await new Promise((resolve) => setTimeout(resolve, interval));
    }
  }

  function follow(jobId, options) {
    const request = options.request;
    const onEvent = options.onEvent || (() => {});
    const onFallback = options.onFallback || (() => {});
    const interval = options.pollInterval || 750;

    function finishFallback(job, resolve, reject) {
      try {
        onFallback(job);
        resolve(job);
      } catch (error) {
        reject(error);
      }
    }

    if (typeof root.EventSource !== "function") {
      return pollJob(jobId, request, interval).then((job) => {
        onFallback(job);
        return job;
      });
    }

    return new Promise((resolve, reject) => {
      let source;
      try {
        source = new root.EventSource(`/api/jobs/${encodeURIComponent(jobId)}/events`);
      } catch (_error) {
        pollJob(jobId, request, interval).then(
          (job) => finishFallback(job, resolve, reject),
          reject,
        );
        return;
      }

      let fallbackStarted = false;
      let finalStatus = "done";
      let result;
      source.onmessage = (event) => {
        let payload;
        try {
          payload = JSON.parse(event.data);
        } catch (_error) {
          return;
        }
        if (payload.type === "status") finalStatus = payload.status || finalStatus;
        if (payload.type === "result") result = payload.result;
        try {
          onEvent(payload);
        } catch (error) {
          source.close();
          reject(error);
          return;
        }
        if (payload.type === "end") {
          source.close();
          resolve({ status: finalStatus, result });
        }
      };
      source.onerror = () => {
        if (fallbackStarted) return;
        fallbackStarted = true;
        source.close();
        pollJob(jobId, request, interval).then(
          (job) => finishFallback(job, resolve, reject),
          reject,
        );
      };
    });
  }

  root.NetScopeJobStream = { follow };
})(window);
