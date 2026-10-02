import { pool, query } from "./db.js";

const tableName = process.env.CONEX_TABLE || "conex";
const limit = Number(process.env.CONEX_LIMIT || 20);

async function fetchConex() {
  try {
    // Mantemos o nome da tabela em uma allowlist simples para evitar SQL invalido.
    if (!/^[a-zA-Z0-9_]+$/.test(tableName)) {
      throw new Error(`Nome de tabela invalido: ${tableName}`);
    }

    const rows = await query(`SELECT * FROM \`${tableName}\` LIMIT ?`, [limit]);

    console.log(`Dados retornados de ${tableName}: ${rows.length} registro(s).`);
    console.table(rows);
  } catch (error) {
    console.error(`Falha ao consultar a tabela ${tableName}.`);
    console.error(error.message);
    process.exitCode = 1;
  } finally {
    await pool.end();
  }
}

fetchConex();
