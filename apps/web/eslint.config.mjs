import next from "eslint-config-next";
const config = [...next, { ignores: [".next/**", "node_modules/**", "playwright-report/**"] }];
export default config;
