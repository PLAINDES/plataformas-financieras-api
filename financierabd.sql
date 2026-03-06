-- MySQL dump 10.13  Distrib 8.0.34, for Win64 (x86_64)
--
-- Host: 127.0.0.1    Database: db_kapitals_core
-- ------------------------------------------------------
-- Server version	8.0.34

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `cms_contact_messages`
--

CREATE DATABASE IF NOT EXISTS db_kapitals_core;

USE db_kapitals_core;

DROP TABLE IF EXISTS `cms_contact_messages`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `cms_contact_messages` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `email` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `phone` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `subject` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `message` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `ip_address` varchar(45) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `user_agent` text COLLATE utf8mb4_unicode_ci,
  `status` enum('unread','read','replied') COLLATE utf8mb4_unicode_ci DEFAULT 'unread',
  `replied_at` datetime DEFAULT NULL,
  `replied_by` bigint unsigned DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `replied_by` (`replied_by`),
  KEY `idx_status` (`status`),
  KEY `idx_created` (`created_at`),
  CONSTRAINT `cms_contact_messages_ibfk_1` FOREIGN KEY (`replied_by`) REFERENCES `sys_users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `cms_contact_messages`
--

LOCK TABLES `cms_contact_messages` WRITE;
/*!40000 ALTER TABLE `cms_contact_messages` DISABLE KEYS */;
/*!40000 ALTER TABLE `cms_contact_messages` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `cms_content_types`
--

DROP TABLE IF EXISTS `cms_content_types`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `cms_content_types` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Nombre técnico (singular): article, service',
  `label` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Nombre legible: Artículo, Servicio',
  `label_plural` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Plural: Artículos, Servicios',
  `content_schema` json DEFAULT NULL,
  `icon` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Icono para UI',
  `is_singleton` tinyint(1) DEFAULT '0' COMMENT 'Si solo puede haber uno (ej: Homepage)',
  `settings` json DEFAULT NULL COMMENT 'Configuración adicional',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_name` (`name`),
  KEY `idx_name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=33 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `cms_content_types`
--

LOCK TABLES `cms_content_types` WRITE;
/*!40000 ALTER TABLE `cms_content_types` DISABLE KEYS */;
INSERT INTO `cms_content_types` VALUES (1,'hero','Hero Section',NULL,'{\"title\": \"string\", \"ctaUrl\": \"string\", \"ctaText\": \"string\", \"description\": \"string\"}',NULL,1,NULL,'2026-01-28 22:49:40','2026-01-28 22:49:40',NULL),(2,'benefits','Benefits Section',NULL,'{\"title\": \"string\", \"subtitle\": \"string\"}',NULL,1,NULL,'2026-01-28 22:49:40','2026-01-28 22:49:40',NULL),(3,'cta','CTA Section',NULL,'{\"description\": \"string\", \"whatsappNumber\": \"string\"}',NULL,1,NULL,'2026-01-28 22:49:40','2026-01-28 22:49:40',NULL),(4,'team_section','Team Section','Team Sections','{\"title\": {\"name\": \"string\", \"caption\": \"string\"}, \"authors\": [{\"id\": \"string\", \"name\": \"string\", \"caption\": \"string\"}], \"collaborators\": [{\"id\": \"string\", \"name\": \"string\", \"image\": \"string\", \"caption\": \"string\", \"description\": \"string\"}], \"developmentTeam\": [{\"id\": \"string\", \"name\": \"string\", \"caption\": \"string\"}]}',NULL,1,NULL,'2026-01-28 23:13:08','2026-01-28 23:13:08',NULL),(10,'platform_card','Platform Card','Platform Cards','{\"title\": \"string\", \"ctaUrl\": \"string\", \"ribbon\": \"string\", \"caption\": \"string\", \"imageUrl\": \"string\", \"videoUrl\": \"string\", \"libraryUrl\": \"string\", \"description\": \"string\", \"hoverVideoUrl\": \"string\"}','cards',0,NULL,'2026-01-29 12:50:25','2026-01-29 12:50:25',NULL),(20,'product_card','Product Card','Product Cards','{\"name\": \"string\", \"price\": \"number\", \"caption\": \"string\", \"typeName\": \"string\"}','shopping-cart',0,NULL,'2026-01-29 12:54:50','2026-01-29 12:54:50',NULL),(30,'section_header','Section Header','Section Headers','{\"title\": \"string\", \"subtitle\": \"string\"}','heading',1,NULL,'2026-01-29 12:58:25','2026-01-29 12:58:25',NULL),(31,'client_logo','Client Logo','Client Logos','{\"alt\": \"string\", \"name\": \"string\", \"imageUrl\": \"string\"}','image',0,NULL,'2026-01-29 12:58:35','2026-01-29 12:58:35',NULL),(32,'contact_section','Contact Section','Contact Sections','{\"form\": {\"fields\": [{\"id\": \"string\", \"rows\": \"number\", \"type\": \"string\", \"label\": \"string\", \"required\": \"boolean\", \"placeholder\": \"string\"}], \"successMessage\": \"string\", \"submitButtonText\": \"string\"}, \"title\": \"string\", \"imageUrl\": \"string\", \"subtitle\": \"string\"}','form',1,NULL,'2026-01-30 12:18:25','2026-01-30 12:18:25',NULL);
/*!40000 ALTER TABLE `cms_content_types` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `cms_contents`
--

DROP TABLE IF EXISTS `cms_contents`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `cms_contents` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `page_id` bigint unsigned DEFAULT NULL,
  `sort_order` int DEFAULT '0',
  `content_type_id` bigint unsigned NOT NULL,
  `slug` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'URL amigable',
  `admin_label` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `data` json NOT NULL COMMENT 'Datos según schema del content_type',
  `status` enum('draft','published','archived') COLLATE utf8mb4_unicode_ci DEFAULT 'draft',
  `is_visible` tinyint(1) DEFAULT '1',
  `published_at` datetime DEFAULT NULL,
  `author_id` bigint unsigned DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `author_id` (`author_id`),
  KEY `idx_content_type` (`content_type_id`),
  KEY `idx_slug` (`slug`),
  KEY `idx_status` (`status`),
  KEY `idx_published` (`published_at`),
  KEY `idx_contents_page_id` (`page_id`),
  CONSTRAINT `cms_contents_ibfk_1` FOREIGN KEY (`content_type_id`) REFERENCES `cms_content_types` (`id`),
  CONSTRAINT `cms_contents_ibfk_2` FOREIGN KEY (`author_id`) REFERENCES `sys_users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=309 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `cms_contents`
--

LOCK TABLES `cms_contents` WRITE;
/*!40000 ALTER TABLE `cms_contents` DISABLE KEYS */;
INSERT INTO `cms_contents` VALUES (1,1,0,1,'hero-home',NULL,'{\"title\": \"Plataforma Financiera\"}','published',1,NULL,NULL,'2026-01-28 22:50:15','2026-02-05 20:39:37',NULL),(2,1,0,2,'benefits-home',NULL,'{\"title\": \"¿Qué tan riesgosa es su industr\", \"subtitle\": \"Revise el riesgo en el que se encuentra su empres\"}','published',1,NULL,NULL,'2026-01-28 22:50:21','2026-02-03 20:40:26',NULL),(3,1,0,3,'cta-home',NULL,'{\"text\": \"Únete a la comunid\", \"whatsappNumber\": \"51987654322\"}','published',1,NULL,NULL,'2026-01-28 22:50:27','2026-02-03 23:45:41',NULL),(4,1,0,4,'team',NULL,'{\"title\": \"Capacitac\", \"authors\": [{\"id\": \"1\", \"name\": \"PhD. Sergio Bravo Orellan\", \"caption\": \"Director de proyecto.\"}], \"collaborators\": [{\"id\": \"1\", \"name\": \"PROIDEAS\", \"image\": \"images/logo.png\", \"caption\": \"Reportes.\", \"description\": \"Área de Consultoría\"}], \"developmentTeam\": [{\"id\": \"1\", \"name\": \"Alvina Calluq\", \"caption\": \"\"}, {\"id\": \"2\", \"name\": \"Yajaira Tácunan Alvarado\", \"caption\": \"\"}, {\"id\": \"3\", \"name\": \"Max Huaccho Zavala\", \"caption\": \"\"}, {\"id\": \"dev-1770151655004\", \"name\": \"Nuevo Miembro\", \"caption\": \"\"}, {\"id\": \"4\", \"name\": \"Albert Camacho\", \"caption\": \"\"}]}','published',1,'2026-01-28 23:14:15',NULL,'2026-01-28 23:14:15','2026-02-05 20:42:10',NULL),(100,NULL,0,10,'platform-card-capital',NULL,'{\"title\": \"Capital\", \"ctaUrl\": \"http://localhost:5173/kapital\", \"ribbon\": \"Nuevo\", \"caption\": \"Calcula tu costo de capital\", \"imageUrl\": \"/images/logo-kapital.png\", \"videoUrl\": \"http://localhost:5173/video/Modulo%20Kapital%20-%20Kapitals.mp4\", \"libraryUrl\": \"https://example.com/biblioteca1\", \"description\": \"Sectorial / De la empresa\", \"hoverVideoUrl\": \"http://localhost:5173/video/Modulo%20Kapital%20-%20Kapitals.mp4\"}','published',1,NULL,NULL,'2026-01-29 12:50:50','2026-01-29 12:50:50',NULL),(101,NULL,0,10,'platform-card-valora',NULL,'{\"title\": \"Valora\", \"ctaUrl\": \"http://localhost:5173/valora\", \"caption\": \"Valorización de empresas\", \"imageUrl\": \"/images/logo-valora.png\", \"videoUrl\": \"http://localhost:5173/video/Modulo%20Valora%20-%20Valora.mp4\", \"libraryUrl\": \"https://example.com/biblioteca2\", \"description\": \"Método FDC descontado / Sensibilidad del Valor\", \"hoverVideoUrl\": \"http://localhost:5173/video/Modulo%20Valora%20-%20Valora.mp4\"}','published',1,NULL,NULL,'2026-01-29 12:51:00','2026-01-29 12:51:00',NULL),(200,NULL,0,20,'kapital-pro',NULL,'{\"name\": \"Kapital Pro\", \"price\": 270, \"caption\": \"Sistema integral de gestión empresarial con módulos de facturación.\", \"typeName\": \"Sistema\"}','published',1,NULL,NULL,'2026-01-29 12:55:31','2026-02-02 14:22:06',NULL),(201,NULL,0,20,'kapital-pos',NULL,'{\"name\": \"Kapital POS\", \"price\": 199, \"caption\": \"Punto de venta completo para tiendas y restaurantes.\", \"typeName\": \"Sistema\"}','published',1,NULL,NULL,'2026-01-29 12:55:39','2026-01-29 12:55:39',NULL),(202,NULL,0,20,'valora-analytics',NULL,'{\"name\": \"Valora Analytics\", \"price\": 399, \"caption\": \"Análisis de datos en tiempo real con dashboard.\", \"typeName\": \"Plataforma\"}','published',1,NULL,NULL,'2026-01-29 12:55:48','2026-01-29 12:55:48',NULL),(203,NULL,0,20,'valora-crm',NULL,'{\"name\": \"Valora CRM\", \"price\": 249, \"caption\": \"Gestión de clientes y ventas con automatización.\", \"typeName\": \"Sistema\"}','published',1,NULL,NULL,'2026-01-29 12:55:57','2026-01-29 12:55:57',NULL),(204,NULL,0,20,'valora-reports',NULL,'{\"name\": \"Valora Reports\", \"price\": 0, \"caption\": \"Generación de reportes financieros automatizados.\", \"typeName\": \"Herramienta\"}','published',1,NULL,NULL,'2026-01-29 12:56:04','2026-01-29 12:56:04',NULL),(300,NULL,0,30,'clients-title',NULL,'{\"text\": \"Ellos confiaron en no\", \"client-text\": \"Ellos confiaron en no\"}','published',1,NULL,NULL,'2026-01-29 12:58:48','2026-02-02 17:01:51',NULL),(301,NULL,0,31,'clients-logos',NULL,'{\"alt\": \"Google logo\", \"name\": \"Google\", \"imageUrl\": \"/images/google-item.png\"}','published',1,NULL,NULL,'2026-01-30 09:47:36','2026-01-30 09:47:36',NULL),(302,NULL,0,31,'clients-logos',NULL,'{\"alt\": \"Microsoft logo\", \"name\": \"Microsoft\", \"imageUrl\": \"/images/microsoft-item.png\"}','published',1,NULL,NULL,'2026-01-30 09:47:36','2026-01-30 09:47:36',NULL),(303,NULL,0,31,'clients-logos',NULL,'{\"alt\": \"Revolut logo\", \"name\": \"Revolut\", \"imageUrl\": \"/images/revolut-item.png\"}','published',1,NULL,NULL,'2026-01-30 09:47:36','2026-01-30 09:47:36',NULL),(304,NULL,0,31,'clients-logos',NULL,'{\"alt\": \"Uber logo\", \"name\": \"Uber\", \"imageUrl\": \"/images/uber-item.png\"}','published',1,NULL,NULL,'2026-01-30 09:47:36','2026-01-30 09:47:36',NULL),(305,1,0,32,'contact-home',NULL,'{\"form\": {\"fields\": [{\"id\": \"name\", \"type\": \"text\", \"label\": \"Nombre y Apellido\", \"required\": true, \"placeholder\": \"Aquí va tu nombre\"}, {\"id\": \"email\", \"type\": \"email\", \"label\": \"Email\", \"required\": true, \"placeholder\": \"you@company.com\"}, {\"id\": \"message\", \"rows\": 4, \"type\": \"textarea\", \"label\": \"Mensaje\", \"required\": true, \"placeholder\": \"Escribe tu mensaje aquí...\"}, {\"id\": \"field-1770161715188\", \"name\": \"field_4\", \"type\": \"text\", \"label\": \"Nuevo Campo\", \"required\": false, \"placeholder\": \"Ingrese información\"}], \"successMessage\": \"¡Mensaje enviado! Nos pondremos en contacto contigo pronto.\", \"submitButtonText\": \"Enviar Mensaje\"}, \"title\": \"Contacta con nosotr\", \"imageUrl\": \"images/web-contact.png\", \"subtitle\": \"¡Estamos aquí para ayudarte\"}','published',1,'2026-01-30 12:19:02',NULL,'2026-01-30 12:19:02','2026-02-03 23:35:27',NULL),(306,1,0,31,'clients',NULL,'{\"logos\": [{\"id\": \"1\", \"alt\": \"Google logo\", \"name\": \"Google\", \"imageUrl\": \"/images/google-item.png\"}, {\"id\": \"3\", \"alt\": \"Revolut logo\", \"name\": \"Revolut\", \"imageUrl\": \"/images/revolut-item.png\"}, {\"id\": \"2\", \"alt\": \"Microsoft logo\", \"name\": \"Microsof\", \"imageUrl\": \"/images/microsoft-item.png\"}, {\"id\": \"client-1770161582236\", \"alt\": \"Uber\", \"name\": \"Uber\", \"imageUrl\": \"/images/uber-item.png\"}], \"title\": \"Ellos confiaron en nosotros\"}','published',1,NULL,NULL,'2026-02-02 15:38:52','2026-02-03 23:33:35',NULL),(307,1,0,10,'platforms',NULL,'{\"items\": [{\"id\": \"uuid-100\", \"name\": \"Capital\", \"ctaUrl\": \"/kapital\", \"ribbon\": \"Nuevo\", \"caption\": \"Calcula tu costo de capital\", \"imageUrl\": \"/images/logo-kapital.png\", \"videoUrl\": \"/video/Modulo-Kapital.mp4\", \"libraryUrl\": \"https://example.com/biblioteca1\", \"description\": \"Sectorial / De la empresa\", \"hoverVideoUrl\": \"/video/Modulo-Kapital-Hover.mp4\"}, {\"id\": \"uuid-101\", \"name\": \"Valore\", \"ctaUrl\": \"/valora\", \"ribbon\": \"\", \"caption\": \"Valorización de empre\", \"imageUrl\": \"/images/logo-valora.png\", \"videoUrl\": \"/video/Modulo-Valora.mp4\", \"libraryUrl\": \"https://example.com/biblioteca2\", \"description\": \"Método FDC descontado / Sensibilidad del Valor\", \"hoverVideoUrl\": \"/video/Modulo-Valora-Hover.mp4\"}, {\"id\": \"card_1770323992085\", \"name\": \"Nuevo Módulo\", \"ctaUrl\": \"https://example.com/curso\", \"caption\": \"Sistema de Gestión\", \"imageUrl\": \"https://via.placeholder.com/300x200/4F46E5/ffffff?text=Nuevo\", \"videoUrl\": \"/video/default.mp4\", \"libraryUrl\": \"https://example.com/biblioteca\", \"description\": \"Descripción del módulo\", \"hoverVideoUrl\": \"/video/default.mp4\"}]}','published',1,NULL,NULL,'2026-02-02 15:49:01','2026-02-05 20:39:55',NULL),(308,1,0,20,'products',NULL,'{\"title\": \"Product\", \"categories\": [{\"id\": \"cat-kapital\", \"label\": \"Kapital\", \"products\": [{\"id\": \"p1\", \"name\": \"Kapital Pro\", \"price\": 270, \"caption\": \"Sistema integral de gestión empresarial con módulos de facturación.\", \"typeName\": \"Sistema\"}, {\"id\": \"p2\", \"name\": \"Kapital PO\", \"price\": 250, \"caption\": \"Punto de venta completo para tiendas y restaurantes.\", \"typeName\": \"Sistema\"}, {\"id\": \"product_1770161751388\", \"name\": \"Nuevo Producto\", \"price\": 0, \"caption\": \"Descripción del producto\", \"typeName\": \"Sistema\"}]}, {\"id\": \"cat-valora\", \"label\": \"Valora\", \"products\": [{\"id\": \"p3\", \"name\": \"Valora Analytics\", \"price\": 399, \"caption\": \"Análisis de datos en tiempo real con dashboard inteligente.\", \"typeName\": \"Plataforma\"}, {\"id\": \"p4\", \"name\": \"Valora CRM\", \"price\": 249, \"caption\": \"Gestión de clientes y ventas con automatización de procesos.\", \"typeName\": \"Sistema\"}, {\"id\": \"p5\", \"name\": \"Valora Reports\", \"price\": 0, \"caption\": \"Generación de reportes financieros automatizados y exportables.\", \"typeName\": \"Herramienta\"}]}], \"products-title\": \"Produc\"}','published',1,NULL,NULL,'2026-02-02 15:54:20','2026-02-03 23:35:53',NULL);
/*!40000 ALTER TABLE `cms_contents` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `cms_media`
--

DROP TABLE IF EXISTS `cms_media`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `cms_media` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `filename` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `original_name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `mime_type` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `size` bigint unsigned DEFAULT NULL COMMENT 'Tamaño en bytes',
  `url` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `storage_path` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `alt_text` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `caption` text COLLATE utf8mb4_unicode_ci,
  `folder` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT '/' COMMENT 'Organización en carpetas',
  `uploaded_by` bigint unsigned DEFAULT NULL,
  `meta` json DEFAULT NULL COMMENT 'Dimensiones, duración, etc',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `uploaded_by` (`uploaded_by`),
  KEY `idx_mime` (`mime_type`),
  KEY `idx_folder` (`folder`),
  CONSTRAINT `cms_media_ibfk_1` FOREIGN KEY (`uploaded_by`) REFERENCES `sys_users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `cms_media`
--

LOCK TABLES `cms_media` WRITE;
/*!40000 ALTER TABLE `cms_media` DISABLE KEYS */;
INSERT INTO `cms_media` VALUES (1,'logo.png','logo.png','image/png',NULL,'/images/logo.png','public/images',NULL,NULL,'branding',NULL,NULL,'2026-01-20 14:13:29','2026-01-20 14:13:29',NULL),(2,'diseñador.png','diseñador.png','image/png',NULL,'/images/diseñador.png','public/images',NULL,NULL,'branding',NULL,NULL,'2026-01-20 14:13:29','2026-01-20 14:13:29',NULL);
/*!40000 ALTER TABLE `cms_media` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `cms_menu_items`
--

DROP TABLE IF EXISTS `cms_menu_items`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `cms_menu_items` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `menu_id` bigint unsigned NOT NULL,
  `parent_id` bigint unsigned DEFAULT NULL COMMENT 'Para submenús',
  `title` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `url` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `page_id` bigint unsigned DEFAULT NULL COMMENT 'Link a página interna',
  `target` enum('_self','_blank') COLLATE utf8mb4_unicode_ci DEFAULT '_self',
  `icon` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `order` int DEFAULT '0',
  `is_visible` tinyint(1) DEFAULT '1',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `page_id` (`page_id`),
  KEY `idx_menu` (`menu_id`,`order`),
  KEY `idx_parent` (`parent_id`),
  CONSTRAINT `cms_menu_items_ibfk_1` FOREIGN KEY (`menu_id`) REFERENCES `cms_menus` (`id`) ON DELETE CASCADE,
  CONSTRAINT `cms_menu_items_ibfk_2` FOREIGN KEY (`parent_id`) REFERENCES `cms_menu_items` (`id`) ON DELETE CASCADE,
  CONSTRAINT `cms_menu_items_ibfk_3` FOREIGN KEY (`page_id`) REFERENCES `cms_pages` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `cms_menu_items`
--

LOCK TABLES `cms_menu_items` WRITE;
/*!40000 ALTER TABLE `cms_menu_items` DISABLE KEYS */;
INSERT INTO `cms_menu_items` VALUES (1,1,NULL,'Plataformas',NULL,NULL,'_self',NULL,1,1,'2026-01-28 16:41:46','2026-01-28 22:34:59'),(2,1,NULL,'Beneficios',NULL,NULL,'_self',NULL,2,1,'2026-01-28 16:41:46','2026-01-28 16:41:46'),(3,1,NULL,'Productos',NULL,NULL,'_self',NULL,3,1,'2026-01-28 16:41:46','2026-01-28 16:41:46'),(4,1,NULL,'Equipo',NULL,NULL,'_self',NULL,4,1,'2026-01-28 16:41:46','2026-01-28 16:41:46'),(5,1,NULL,'Contacto',NULL,NULL,'_self',NULL,5,1,'2026-01-28 16:41:46','2026-01-28 16:41:46');
/*!40000 ALTER TABLE `cms_menu_items` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `cms_menus`
--

DROP TABLE IF EXISTS `cms_menus`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `cms_menus` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'header, footer, sidebar',
  `label` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `cms_menus`
--

LOCK TABLES `cms_menus` WRITE;
/*!40000 ALTER TABLE `cms_menus` DISABLE KEYS */;
INSERT INTO `cms_menus` VALUES (1,'header_landing','Menú Landing Page','2026-01-19 11:45:58','2026-01-28 16:35:18'),(2,'footer_landing','Menú Footer Landing','2026-01-19 11:45:58','2026-01-28 16:38:54');
/*!40000 ALTER TABLE `cms_menus` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `cms_pages`
--

DROP TABLE IF EXISTS `cms_pages`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `cms_pages` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `title` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `slug` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `template` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT 'default' COMMENT 'Template a usar',
  `parent_id` bigint unsigned DEFAULT NULL COMMENT 'Para páginas anidadas',
  `status` enum('draft','published') COLLATE utf8mb4_unicode_ci DEFAULT 'draft',
  `order` int DEFAULT '0',
  `is_homepage` tinyint(1) DEFAULT '0',
  `settings` json DEFAULT NULL COMMENT 'Configuración de página',
  `seo_title` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `seo_description` text COLLATE utf8mb4_unicode_ci,
  `seo_image` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `slug` (`slug`),
  KEY `idx_slug` (`slug`),
  KEY `idx_status` (`status`),
  KEY `idx_parent` (`parent_id`),
  CONSTRAINT `cms_pages_ibfk_1` FOREIGN KEY (`parent_id`) REFERENCES `cms_pages` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `cms_pages`
--

LOCK TABLES `cms_pages` WRITE;
/*!40000 ALTER TABLE `cms_pages` DISABLE KEYS */;
INSERT INTO `cms_pages` VALUES (1,'Inicio','home','landing',NULL,'published',0,1,'{\"layout\": \"full\", \"show_footer\": true, \"show_header\": true}','Plataforma Finanzas | Inicio','Plataforma Finanzas - Soluciones financieras modernas',NULL,'2026-01-21 09:27:58','2026-01-21 09:27:58',NULL);
/*!40000 ALTER TABLE `cms_pages` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `cms_section_contents`
--

DROP TABLE IF EXISTS `cms_section_contents`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `cms_section_contents` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `section_id` bigint unsigned NOT NULL,
  `content_id` bigint unsigned NOT NULL,
  `order` int DEFAULT '0',
  `is_visible` tinyint(1) DEFAULT '1',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_section_content` (`section_id`,`content_id`),
  KEY `fk_sc_content` (`content_id`),
  CONSTRAINT `fk_sc_content` FOREIGN KEY (`content_id`) REFERENCES `cms_contents` (`id`),
  CONSTRAINT `fk_sc_section` FOREIGN KEY (`section_id`) REFERENCES `cms_sections` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=18 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `cms_section_contents`
--

LOCK TABLES `cms_section_contents` WRITE;
/*!40000 ALTER TABLE `cms_section_contents` DISABLE KEYS */;
INSERT INTO `cms_section_contents` VALUES (1,1,1,0,1,'2026-01-29 12:07:06','2026-01-29 12:07:06'),(2,2,3,1,1,'2026-01-29 12:07:20','2026-01-30 08:30:40'),(3,3,2,2,1,'2026-01-29 12:07:29','2026-01-30 10:44:20'),(4,4,4,0,1,'2026-01-29 12:07:40','2026-01-29 12:07:40'),(5,20,100,0,1,'2026-01-29 12:51:09','2026-01-29 12:51:09'),(6,20,101,1,1,'2026-01-29 12:51:09','2026-01-29 12:51:09'),(7,30,200,0,1,'2026-01-29 12:56:11','2026-01-29 12:56:11'),(8,30,201,1,1,'2026-01-29 12:56:11','2026-01-29 12:56:11'),(9,31,202,0,1,'2026-01-29 12:56:19','2026-01-29 12:56:19'),(10,31,203,1,1,'2026-01-29 12:56:19','2026-01-29 12:56:19'),(11,31,204,2,1,'2026-01-29 12:56:19','2026-01-29 12:56:19'),(12,40,300,0,1,'2026-01-29 12:59:21','2026-01-29 12:59:21'),(13,40,301,1,1,'2026-01-30 09:48:31','2026-01-30 09:48:31'),(14,40,302,2,1,'2026-01-30 09:48:31','2026-01-30 09:48:31'),(15,40,303,3,1,'2026-01-30 09:48:31','2026-01-30 09:48:31'),(16,40,304,4,1,'2026-01-30 09:48:31','2026-01-30 09:48:31'),(17,41,305,0,1,'2026-01-30 12:19:41','2026-01-30 12:19:41');
/*!40000 ALTER TABLE `cms_section_contents` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `cms_sections`
--

DROP TABLE IF EXISTS `cms_sections`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `cms_sections` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `page_id` bigint unsigned NOT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `component` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Componente React a renderizar',
  `order` int DEFAULT '0',
  `is_visible` tinyint(1) DEFAULT '1',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_page` (`page_id`),
  KEY `idx_order` (`page_id`,`order`),
  CONSTRAINT `cms_sections_ibfk_1` FOREIGN KEY (`page_id`) REFERENCES `cms_pages` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=42 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `cms_sections`
--

LOCK TABLES `cms_sections` WRITE;
/*!40000 ALTER TABLE `cms_sections` DISABLE KEYS */;
INSERT INTO `cms_sections` VALUES (1,1,'hero-home','HeroSection',1,1,'2026-01-29 10:54:57','2026-01-29 10:54:57',NULL),(2,1,'cta-home','CTASection',3,1,'2026-01-29 10:55:03','2026-01-29 10:55:03',NULL),(3,1,'benefits-home','BenefitsSection',4,1,'2026-01-29 10:55:08','2026-01-29 10:55:08',NULL),(4,1,'team-home','TeamSection',5,1,'2026-01-29 10:55:24','2026-02-02 12:11:06',NULL),(20,1,'platform','PlatformSection',2,1,'2026-01-29 12:50:39','2026-01-29 12:50:39',NULL),(30,1,'products-kapital','ProductsSection',3,1,'2026-01-29 12:55:16','2026-01-29 12:55:16',NULL),(31,1,'products-valora','ProductsSection',4,1,'2026-01-29 12:55:24','2026-01-29 12:55:24',NULL),(40,1,'clients-home','ClientsSection',5,1,'2026-01-29 12:58:41','2026-02-02 11:15:48',NULL),(41,1,'contact-home','ContactSection',6,1,'2026-01-30 12:19:14','2026-02-02 13:43:04',NULL);
/*!40000 ALTER TABLE `cms_sections` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `cms_site_settings`
--

DROP TABLE IF EXISTS `cms_site_settings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `cms_site_settings` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `site_key` varchar(50) NOT NULL,
  `header_logo_id` bigint unsigned DEFAULT NULL,
  `header_logo_sticky_id` bigint unsigned DEFAULT NULL,
  `favicon_id` bigint unsigned DEFAULT NULL,
  `meta` json DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `site_key` (`site_key`),
  KEY `fk_header_logo` (`header_logo_id`),
  CONSTRAINT `fk_header_logo` FOREIGN KEY (`header_logo_id`) REFERENCES `cms_media` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `cms_site_settings`
--

LOCK TABLES `cms_site_settings` WRITE;
/*!40000 ALTER TABLE `cms_site_settings` DISABLE KEYS */;
INSERT INTO `cms_site_settings` VALUES (1,'main',1,NULL,NULL,'{\"theme\": \"default\", \"site_name\": \"Plataforma Finanzas\", \"primary_color\": \"#009ef7\"}','2026-01-20 15:33:07','2026-01-20 15:33:07');
/*!40000 ALTER TABLE `cms_site_settings` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `fin_companies`
--

DROP TABLE IF EXISTS `fin_companies`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `fin_companies` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `industry_id` bigint unsigned DEFAULT NULL,
  `ticker` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `description` text COLLATE utf8mb4_unicode_ci,
  `metadata` json DEFAULT NULL COMMENT 'Datos adicionales',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_industry` (`industry_id`),
  KEY `idx_ticker` (`ticker`),
  CONSTRAINT `fin_companies_ibfk_1` FOREIGN KEY (`industry_id`) REFERENCES `fin_industries` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `fin_companies`
--

LOCK TABLES `fin_companies` WRITE;
/*!40000 ALTER TABLE `fin_companies` DISABLE KEYS */;
/*!40000 ALTER TABLE `fin_companies` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `fin_industries`
--

DROP TABLE IF EXISTS `fin_industries`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `fin_industries` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `code` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `description` text COLLATE utf8mb4_unicode_ci,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `fin_industries`
--

LOCK TABLES `fin_industries` WRITE;
/*!40000 ALTER TABLE `fin_industries` DISABLE KEYS */;
/*!40000 ALTER TABLE `fin_industries` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `fin_reports`
--

DROP TABLE IF EXISTS `fin_reports`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `fin_reports` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `template_id` bigint unsigned NOT NULL,
  `company_id` bigint unsigned DEFAULT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `code` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Código único del reporte',
  `type` enum('valora','kapital') COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` enum('draft','processing','completed','error') COLLATE utf8mb4_unicode_ci DEFAULT 'draft',
  `input_data` json DEFAULT NULL COMMENT 'Datos de entrada del usuario',
  `output_data` json DEFAULT NULL COMMENT 'Resultados calculados',
  `file_path` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Excel generado',
  `file_generated_at` datetime DEFAULT NULL,
  `error_message` text COLLATE utf8mb4_unicode_ci,
  `is_public` tinyint(1) DEFAULT '0' COMMENT 'Si se puede compartir',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `template_id` (`template_id`),
  KEY `company_id` (`company_id`),
  KEY `idx_user` (`user_id`),
  KEY `idx_type` (`type`),
  KEY `idx_status` (`status`),
  KEY `idx_code` (`code`),
  CONSTRAINT `fin_reports_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `sys_users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fin_reports_ibfk_2` FOREIGN KEY (`template_id`) REFERENCES `fin_templates` (`id`),
  CONSTRAINT `fin_reports_ibfk_3` FOREIGN KEY (`company_id`) REFERENCES `fin_companies` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `fin_reports`
--

LOCK TABLES `fin_reports` WRITE;
/*!40000 ALTER TABLE `fin_reports` DISABLE KEYS */;
/*!40000 ALTER TABLE `fin_reports` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `fin_sales`
--

DROP TABLE IF EXISTS `fin_sales`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `fin_sales` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `report_id` bigint unsigned NOT NULL,
  `buyer_id` bigint unsigned DEFAULT NULL COMMENT 'Usuario que compró (NULL si es público)',
  `email` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `amount` decimal(10,2) NOT NULL,
  `currency` varchar(3) COLLATE utf8mb4_unicode_ci DEFAULT 'PEN',
  `payment_method` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `payment_code` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Código de transacción',
  `payment_file` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Comprobante subido',
  `status` enum('pending','verified','rejected') COLLATE utf8mb4_unicode_ci DEFAULT 'pending',
  `verified_at` datetime DEFAULT NULL,
  `verified_by` bigint unsigned DEFAULT NULL,
  `ip_address` varchar(45) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `notes` text COLLATE utf8mb4_unicode_ci,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `verified_by` (`verified_by`),
  KEY `idx_report` (`report_id`),
  KEY `idx_buyer` (`buyer_id`),
  KEY `idx_status` (`status`),
  CONSTRAINT `fin_sales_ibfk_1` FOREIGN KEY (`report_id`) REFERENCES `fin_reports` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fin_sales_ibfk_2` FOREIGN KEY (`buyer_id`) REFERENCES `sys_users` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fin_sales_ibfk_3` FOREIGN KEY (`verified_by`) REFERENCES `sys_users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `fin_sales`
--

LOCK TABLES `fin_sales` WRITE;
/*!40000 ALTER TABLE `fin_sales` DISABLE KEYS */;
/*!40000 ALTER TABLE `fin_sales` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `fin_templates`
--

DROP TABLE IF EXISTS `fin_templates`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `fin_templates` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `code` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'valora_dcf, kapital_wacc',
  `type` enum('valora','kapital') COLLATE utf8mb4_unicode_ci NOT NULL,
  `file_path` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Ruta del template Excel',
  `version` int DEFAULT '1',
  `schema` json DEFAULT NULL COMMENT 'Estructura de datos esperada',
  `is_active` tinyint(1) DEFAULT '1',
  `description` text COLLATE utf8mb4_unicode_ci,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_code_version` (`code`,`version`),
  KEY `idx_type` (`type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `fin_templates`
--

LOCK TABLES `fin_templates` WRITE;
/*!40000 ALTER TABLE `fin_templates` DISABLE KEYS */;
/*!40000 ALTER TABLE `fin_templates` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `sys_sessions`
--

DROP TABLE IF EXISTS `sys_sessions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `sys_sessions` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `token` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `ip_address` varchar(45) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `user_agent` text COLLATE utf8mb4_unicode_ci,
  `expires_at` datetime NOT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_token` (`token`(255)),
  KEY `idx_user` (`user_id`),
  CONSTRAINT `sys_sessions_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `sys_users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=28 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `sys_sessions`
--

LOCK TABLES `sys_sessions` WRITE;
/*!40000 ALTER TABLE `sys_sessions` DISABLE KEYS */;
INSERT INTO `sys_sessions` VALUES (1,16,'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxNiIsImV4cCI6MTc2ODk1NDQ4N30.sGNUSXzI8C0gRUxGiMYhutxIWYGa94X1QcgqR7ajDx0',NULL,NULL,'2026-01-21 00:14:47','2026-01-19 19:14:47'),(2,14,'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxNCIsImV4cCI6MTc2ODk1NDUzMX0.L7macaJCJBFb6WyPwT6Whqrqp_wOo4EMocuA_y6smnU',NULL,NULL,'2026-01-21 00:15:31','2026-01-19 19:15:31'),(5,15,'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxNSIsImV4cCI6MTc2OTA5NDQyMn0.HvfAi1O1M7lVkNlzGVD9K-CCVu7S8KzpebAi-bj0IY8',NULL,NULL,'2026-01-22 15:07:02','2026-01-21 10:07:02'),(6,15,'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxNSIsImV4cCI6MTc2OTA5NzUxMn0.ur386KYoNKp6ri8njRBWLWpn-o34j3AZwMuSW0BEhzk',NULL,NULL,'2026-01-22 15:58:33','2026-01-21 10:58:32'),(7,15,'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxNSIsImV4cCI6MTc2OTUyMjY1Nn0.tmdIqtSgAlN6Ts91-4-U-8b3wRmmAjGeh_cX-MFEA2M',NULL,NULL,'2026-01-27 14:04:17','2026-01-26 09:04:16'),(8,15,'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxNSIsImV4cCI6MTc2OTUzNzg2N30.xpeoYR1O60fazub_sL7JSo_UMHdCkyvcYLT1uBn8EiU',NULL,NULL,'2026-01-27 18:17:47','2026-01-26 13:17:47'),(9,15,'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxNSIsImV4cCI6MTc2OTU0OTc2NH0.PXM3nErHxRq50fsr_qKVHsJzsGigOjtBa6Vo0VDgQQs',NULL,NULL,'2026-01-27 21:36:05','2026-01-26 16:36:04'),(10,15,'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxNSIsImV4cCI6MTc2OTU1Mzc4MX0.cahcT26y3c1tX8-r5u28nkuwNnxL0JkPc5utRDGlxkE',NULL,NULL,'2026-01-27 22:43:02','2026-01-26 17:43:01'),(11,15,'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxNSIsImV4cCI6MTc2OTU3NDE0NX0.iwySoGcGiWr3uJ1d7ROGcU89UtAtCOGZ-NZIXOmHqms',NULL,NULL,'2026-01-28 04:22:26','2026-01-26 23:22:26'),(12,15,'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxNSIsImV4cCI6MTc2OTcyMjE4MX0.qNkAbqSiNngL0jfPZpQBVbHsyj1JwpvKVY_lYJXjHLI',NULL,NULL,'2026-01-29 21:29:42','2026-01-28 16:29:41'),(13,15,'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxNSIsImV4cCI6MTc2OTc0NDE3Nn0.Qgyw9pIP5JMCALRHkdGi5drtFRRRLmrwgwr4NagrMlg',NULL,NULL,'2026-01-30 03:36:17','2026-01-28 22:36:16'),(15,15,'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxNSIsImV4cCI6MTc2OTgwNDQ0Mn0.76w66G9l8WN6jT9XzkdNPsrRr0kfeSLyo57kSd_S-YY',NULL,NULL,'2026-01-30 20:20:42','2026-01-29 15:20:42'),(19,15,'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxNSIsImV4cCI6MTc2OTg4NzgxNn0.V2e076zZGtYpFyAqs6id28S4YR_jmN3sjll3DumA7Cc',NULL,NULL,'2026-01-31 19:30:16','2026-01-30 14:30:16'),(23,15,'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxNSIsImV4cCI6MTc2OTg5NjU5OH0.O8n2ca2W55LAyJUcWL5mz6cfM7zWoytH1FNXqB3hoLM',NULL,NULL,'2026-01-31 21:56:39','2026-01-30 16:56:38'),(24,15,'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxNSIsImV4cCI6MTc3MDEyOTI3N30.w7CQizyfJzTWjv6OJUgSc9slAYTXyPsnTdcilU0KfFQ',NULL,NULL,'2026-02-03 14:34:38','2026-02-02 09:34:37'),(25,15,'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxNSIsImV4cCI6MTc3MDIyMzExM30.CKxxmqf8KXFQ0W73fIYBYNHMdh1JK0SWg2fEnQ2MaZ0',NULL,NULL,'2026-02-04 16:38:34','2026-02-03 11:38:33'),(26,15,'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxNSIsImV4cCI6MTc3MDIzNTI2OX0.sON3IwhO9M0-fYsinh4TBcq-ULXD3Dht94ikUrbsz9E',NULL,NULL,'2026-02-04 20:01:09','2026-02-03 15:01:09'),(27,15,'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxNSIsImV4cCI6MTc3MDQxMDM3MH0.Il9-HltXLLsUzAswi8mV7LuDgeCCkE2I-b7jP9Qhqwk',NULL,NULL,'2026-02-06 20:39:30','2026-02-05 15:39:30');
/*!40000 ALTER TABLE `sys_sessions` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `sys_settings`
--

DROP TABLE IF EXISTS `sys_settings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `sys_settings` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `key` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `value` json NOT NULL,
  `type` enum('text','json','boolean','number') COLLATE utf8mb4_unicode_ci DEFAULT 'text',
  `description` text COLLATE utf8mb4_unicode_ci,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `key` (`key`),
  KEY `idx_key` (`key`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `sys_settings`
--

LOCK TABLES `sys_settings` WRITE;
/*!40000 ALTER TABLE `sys_settings` DISABLE KEYS */;
INSERT INTO `sys_settings` VALUES (1,'site_name','\"Kapitals\"','text','Nombre del sitio','2026-01-19 11:45:58'),(2,'site_logo','\"/images/logo.png\"','text','Logo del sitio','2026-01-19 11:45:58'),(3,'contact_email','\"contacto@kapitals.com\"','text','Email de contacto','2026-01-19 11:45:58');
/*!40000 ALTER TABLE `sys_settings` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `sys_users`
--

DROP TABLE IF EXISTS `sys_users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `sys_users` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `email` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `password` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `lastname` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `role` enum('master','admin','user') COLLATE utf8mb4_unicode_ci DEFAULT 'user',
  `is_active` tinyint(1) DEFAULT '1',
  `avatar` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `settings` json DEFAULT NULL COMMENT 'Preferencias de usuario',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `email` (`email`),
  KEY `idx_email` (`email`),
  KEY `idx_role` (`role`)
) ENGINE=InnoDB AUTO_INCREMENT=17 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `sys_users`
--

LOCK TABLES `sys_users` WRITE;
/*!40000 ALTER TABLE `sys_users` DISABLE KEYS */;
INSERT INTO `sys_users` VALUES (1,'admin@kapitals.com','$2b$10$rEjKZxRk5YwVqVLVjVZcceZwYqWZqYxGvHXqXqYxGvHXq','Admin','Kapitals','admin',1,NULL,NULL,'2026-01-19 11:45:58','2026-01-19 11:45:58',NULL),(14,'user@example.com','$2b$12$VFelhCJtzYuuJ3Fwj7LqRu0WQTj6ZmBWx.HaSNxbOTNwk1YKXnh7u','string','string','user',1,NULL,NULL,'2026-01-19 19:11:06','2026-01-19 19:11:06',NULL),(15,'sabeteta03@gmail.com','$2b$12$oT/hn.hnQfUHMuAnGTW6j.BbocKPiM5zeYVJ2yvcga.aeyRz5yAjW','Sebastian','Beteta','admin',1,NULL,NULL,'2026-01-19 19:12:21','2026-01-20 09:04:47',NULL),(16,'s.beteta.e03@gmail.com','$2b$12$tosr1nUX/DMKJg4zTQgA.uni4ZzrPsxAKUvcZaqEcJSH5mgSrQQNm','Adauco','Espinoza','user',1,NULL,NULL,'2026-01-19 19:14:47','2026-01-19 19:14:47',NULL);
/*!40000 ALTER TABLE `sys_users` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-02-05 17:11:09
