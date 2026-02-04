-- phpMyAdmin SQL Dump
-- version 5.2.1
-- https://www.phpmyadmin.net/
--
-- Host: 127.0.0.1
-- Generation Time: Jan 02, 2026 at 05:22 PM
-- Server version: 10.4.32-MariaDB
-- PHP Version: 8.0.30

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Database: `trading_app`
--

-- --------------------------------------------------------

--
-- Table structure for table `stocks`
--

CREATE TABLE IF NOT EXIST `stocks` (
  `Symbols` varchar(20) NOT NULL,
  `Company_names` varchar(100) DEFAULT NULL,
  `Category` varchar(30) NOT NULL,
  `Previous_ClosePrice` double DEFAULT NULL,
  `Today_OpenPrice` double DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `stocks`
--

INSERT INTO `stocks` (`Symbols`, `Company_names`, `Category`, `Previous_ClosePrice`, `Today_OpenPrice`) VALUES
('ADANIENT', 'Adani Enterprises', 'Energy', 2975, 2995),
('ADANIGREEN', 'Adani Green Energy', 'Energy', 1020, 1035),
('ADANIPORTS', 'Adani Ports', 'Infra & Materials', 1225, 1230),
('ADANITRANS', 'Adani Transmission', 'Energy', 810, 820),
('ASIANPAINT', 'Asian Paints', 'FMCG', 3280, 3300),
('AXISBANK', 'Axis Bank', 'Banking', 1182, 1185.75),
('BAJAJ-AUTO', 'Bajaj Auto', 'Automobile', 7600, 7650),
('BAJAJFINSV', 'Bajaj Finserv', 'Financial Services', 1680.6, 1690.1),
('BAJFINANCE', 'Bajaj Finance', 'Financial Services', 7050, 7100),
('BHARTIARTL', 'Bharti Airtel', 'Telecom', 1240, 1250),
('BPCL', 'Bharat Petroleum', 'Energy', 570, 575),
('BRITANNIA', 'Britannia Industries', 'FMCG', 5100, 5150),
('CIPLA', 'Cipla Ltd.', 'Pharma', 1350, 1365),
('COALINDIA', 'Coal India', 'Energy', 460, 462),
('DIVISLAB', 'Divi\'s Laboratories', 'Pharma', 4150, 4170),
('DRREDDY', 'Dr. Reddy\'s Laboratories', 'Pharma', 5980, 6025),
('EICHERMOT', 'Eicher Motors', 'Automobile', 4050, 4080),
('GRASIM', 'Grasim Industries', 'Infra & Materials', 2100, 2120),
('HCLTECH', 'HCL Technologies', 'IT', 1230.3, 1235),
('HDFCBANK', 'HDFC Bank', 'Banking', 1650.35, 1660),
('HDFCLIFE', 'HDFC Life Insurance', 'Financial Services', 600, 605),
('HEROMOTOCO', 'Hero MotoCorp', 'Automobile', 5000, 5050),
('HINDALCO', 'Hindalco Industries', 'Infra & Materials', 560, 565),
('HINDUNILVR', 'Hindustan Unilever', 'FMCG', 2560, 2585),
('ICICIBANK', 'ICICI Bank', 'Banking', 1015, 1019.8),
('ICICIPRULI', 'ICICI Prudential Life', 'Financial Services', 570, 575),
('INDUSINDBK', 'IndusInd Bank', 'Banking', 1480, 1490),
('INFY', 'Infosys', 'IT', 1622.75, 1627.5),
('IOC', 'Indian Oil Corp.', 'Energy', 170, 172),
('ITC', 'ITC Ltd.', 'FMCG', 456.1, 457.8),
('JSWSTEEL', 'JSW Steel', 'Infra & Materials', 920, 925),
('KOTAKBANK', 'Kotak Mahindra Bank', 'Banking', 1755.25, 1762.4),
('LT', 'Larsen & Toubro', 'Infra & Materials', 3820, 3840),
('M&M', 'Mahindra & Mahindra', 'Automobile', 1640, 1655),
('MARUTI', 'Maruti Suzuki', 'Automobile', 11280, 11310),
('NESTLEIND', 'Nestle India', 'FMCG', 24800, 24950),
('NTPC', 'NTPC Ltd.', 'Energy', 305, 308),
('ONGC', 'Oil & Natural Gas Corp.', 'Energy', 287.4, 288.5),
('POWERGRID', 'Power Grid Corp.', 'Energy', 280, 282),
('RELIANCE', 'Reliance Industries', 'Energy', 2711.5, 2720),
('SBILIFE', 'SBI Life Insurance', 'Financial Services', 1470, 1480),
('SBIN', 'State Bank of India', 'Banking', 755.9, 760.5),
('SUNPHARMA', 'Sun Pharma', 'Pharma', 1305, 1310),
('TATACONSUM', 'Tata Consumer Products', 'FMCG', 1220, 1230),
('TATAMOTORS', 'Tata Motors', 'Automobile', 875, 880),
('TATASTEEL', 'Tata Steel', 'Infra & Materials', 140.2, 142),
('TCS', 'Tata Consultancy Services', 'IT', 3456.1, 3462),
('TECHM', 'Tech Mahindra', 'IT', 1215.2, 1218.75),
('TITAN', 'Titan Company', 'FMCG', 3381.55, 3475),
('ULTRACEMCO', 'UltraTech Cement', 'Infra & Materials', 9300, 9355),
('WIPRO', 'Wipro Ltd.', 'IT', 423.55, 425.2);

--
-- Indexes for dumped tables
--

--
-- Indexes for table `stocks`
--
ALTER TABLE `stocks`
  ADD PRIMARY KEY (`Symbols`);
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
