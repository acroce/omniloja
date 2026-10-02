import { pool } from "./db.js";

async function testConnection() {
  try {
    const connection = await pool.getConnection();
    const [rows] = await connection.query("SELECT NOW() AS server_time");
    connection.release();

    console.log("Conexao com MySQL realizada com sucesso.");
    console.table(rows);
  } catch (error) {
    console.error("Falha ao conectar no MySQL.");
    console.error(error.message);
    process.exitCode = 1;
  } finally {
    await pool.end();
  }
}

testConnection();
