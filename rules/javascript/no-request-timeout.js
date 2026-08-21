const request = require("request");

// ruleid: no-request-timeout
request.get(url);

// ruleid: no-request-timeout
request.post(endpoint, { json: payload });

// ruleid: no-request-timeout
request.put(api, body, { json: true });

// ok: no-request-timeout
request.get(url, { timeout: 10000 });

// ok: no-request-timeout
request.post(endpoint, { json: payload, timeout: 5000 });

// ok: no-request-timeout
axios.get(url, { timeout: 5000 });