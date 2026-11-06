// Steady user traffic for the checkout service, so the SLOs always have data.
// Locally: k6 run -e BASE_URL=http://localhost:8000 -e DURATION=1m deploy/k8s/loadgen/checkout.js
import http from "k6/http";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";

export const options = {
  discardResponseBodies: true,
  scenarios: {
    steady: {
      executor: "constant-arrival-rate",
      rate: Number(__ENV.RATE || 10), // requests per second
      timeUnit: "1s",
      duration: __ENV.DURATION || "720h",
      preAllocatedVUs: 10,
      maxVUs: 50,
    },
  },
};

export default function () {
  http.get(`${BASE_URL}/checkout`, { tags: { name: "checkout" } });
}
