using Microsoft.Data.SqlClient;
using System;
using System.Data;
using System.Windows.Forms;

namespace ElHareketleriPanel
{
    public partial class Form1 : Form
    {
        string connectionString =
            "Server=localhost\\SQLEXPRESS;Database=ElKontrolDB;Trusted_Connection=True;TrustServerCertificate=True;";

        DataGridView dataGridView1 = new DataGridView();
        Button btnYenile = new Button();
        Label lblToplam = new Label();
        Label lblSolTik = new Label();
        Label lblSagTik = new Label();

        public Form1()
        {
            InitializeComponent();
            ArayuzuOlustur();
        }

        private void ArayuzuOlustur()
        {
            this.Text = "El Hareketleri Kontrol Paneli";
            this.Width = 1000;
            this.Height = 600;

            lblToplam.SetBounds(20, 20, 200, 30);
            lblSolTik.SetBounds(240, 20, 150, 30);
            lblSagTik.SetBounds(410, 20, 150, 30);

            btnYenile.Text = "Yenile";
            btnYenile.SetBounds(600, 15, 100, 35);
            btnYenile.Click += btnYenile_Click;

            dataGridView1.SetBounds(20, 70, 940, 450);
            dataGridView1.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill;

            this.Controls.Add(lblToplam);
            this.Controls.Add(lblSolTik);
            this.Controls.Add(lblSagTik);
            this.Controls.Add(btnYenile);
            this.Controls.Add(dataGridView1);

            this.Load += Form1_Load;
        }

        private void Form1_Load(object sender, EventArgs e)
        {
            KayitlariGetir();
            IstatistikleriGetir();
        }

        private void btnYenile_Click(object sender, EventArgs e)
        {
            KayitlariGetir();
            IstatistikleriGetir();
        }

        private void KayitlariGetir()
        {
            using (SqlConnection conn = new SqlConnection(connectionString))
            {
                string query = "SELECT Id, HareketAdi, ModAdi, ElTipi, TarihSaat FROM HareketKayitlari ORDER BY Id DESC";
                SqlDataAdapter da = new SqlDataAdapter(query, conn);
                DataTable dt = new DataTable();
                da.Fill(dt);
                dataGridView1.DataSource = dt;
            }
        }

        private void IstatistikleriGetir()
        {
            using (SqlConnection conn = new SqlConnection(connectionString))
            {
                conn.Open();

                lblToplam.Text = "Toplam Hareket: " + KomutSay(conn, "SELECT COUNT(*) FROM HareketKayitlari");
                lblSolTik.Text = "Sol Týk: " + KomutSay(conn, "SELECT COUNT(*) FROM HareketKayitlari WHERE HareketAdi='Sol Tik'");
                lblSagTik.Text = "Sað Týk: " + KomutSay(conn, "SELECT COUNT(*) FROM HareketKayitlari WHERE HareketAdi='Sag Tik'");
            }
        }

        private int KomutSay(SqlConnection conn, string query)
        {
            using (SqlCommand cmd = new SqlCommand(query, conn))
            {
                return Convert.ToInt32(cmd.ExecuteScalar());
            }
        }
    }
}