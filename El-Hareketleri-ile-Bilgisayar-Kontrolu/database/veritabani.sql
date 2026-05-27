USE [ElKontrolDB]
GO

SET ANSI_NULLS ON
GO

SET QUOTED_IDENTIFIER ON
GO

CREATE TABLE [dbo].[HareketKayitlari](
    [Id] [int] IDENTITY(1,1) NOT NULL,
    [HareketAdi] [nvarchar](100) NULL,
    [ModAdi] [nvarchar](50) NULL,
    [ElTipi] [nvarchar](50) NULL,
    [TarihSaat] [datetime] NULL,
PRIMARY KEY CLUSTERED
(
    [Id] ASC
)
) ON [PRIMARY]
GO

ALTER TABLE [dbo].[HareketKayitlari]
ADD DEFAULT (getdate()) FOR [TarihSaat]
GO