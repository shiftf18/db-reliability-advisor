const appDb = db.getSiblingDB("reliability_demo");
appDb.createUser({
  user: "app_user",
  pwd: "app_password",
  roles: [
    { role: "readWrite", db: "reliability_demo" },
    { role: "clusterMonitor", db: "admin" },
  ],
});
appDb.createCollection("orders");
appDb.orders.createIndex(
  { customerId: 1, status: 1, createdAt: -1 },
  { name: "customer_status_created_at" },
);

const adminDb = db.getSiblingDB("admin");
adminDb.createUser({
  user: "exporter_monitor",
  pwd: "exporter_password",
  roles: [
    { role: "clusterMonitor", db: "admin" },
    { role: "read", db: "local" },
  ],
});
