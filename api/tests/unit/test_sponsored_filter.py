"""Tests for sponsored link filtering."""

from menos.services.sponsored_filter import SponsoredFilter


class TestSponsoredFilter:
    """Test suite for SponsoredFilter."""

    def setup_method(self):
        """Set up test fixtures."""
        self.filter = SponsoredFilter()

    def test_amazon_affiliate_link_detected(self):
        """Test that Amazon affiliate links are detected."""
        url = "https://amazon.com/product?tag=affiliate123"
        assert self.filter.is_sponsored_link(url) is True

    def test_amazon_aws_link_not_sponsored(self):
        """Test that Amazon AWS links are not flagged as sponsored."""
        url = "https://aws.amazon.com/s3/pricing/"
        context = "Learn about AWS S3 storage pricing"
        assert self.filter.is_sponsored_link(url, context) is False

    def test_amazon_aws_documentation_not_sponsored(self):
        """Test that AWS documentation is not flagged."""
        url = "https://docs.aws.amazon.com/lambda/latest/dg/welcome.html"
        context = "AWS Lambda documentation for serverless functions"
        assert self.filter.is_sponsored_link(url, context) is False

    def test_amazon_without_aws_context_is_sponsored(self):
        """Test that Amazon links without AWS context are flagged."""
        url = "https://amazon.com/books/programming"
        context = "Check out these programming books"
        assert self.filter.is_sponsored_link(url, context) is True

    def test_short_link_bit_ly(self):
        """Test that bit.ly short links are detected."""
        url = "https://bit.ly/3xYz123"
        assert self.filter.is_sponsored_link(url) is True

    def test_short_link_amzn_to(self):
        """Test that amzn.to short links are detected."""
        url = "https://amzn.to/3abc456"
        assert self.filter.is_sponsored_link(url) is True

    def test_short_link_geni_us(self):
        """Test that geni.us short links are detected."""
        url = "https://geni.us/product123"
        assert self.filter.is_sponsored_link(url) is True

    def test_short_link_tinyurl(self):
        """Test that tinyurl.com links are detected."""
        url = "https://tinyurl.com/abc123"
        assert self.filter.is_sponsored_link(url) is True

    def test_utm_source_parameter(self):
        """Test that UTM tracking parameters are detected."""
        url = "https://example.com/article?utm_source=newsletter&utm_campaign=promo"
        assert self.filter.is_sponsored_link(url) is True

    def test_ref_parameter(self):
        """Test that ref= parameters are detected."""
        url = "https://example.com/product?ref=influencer123"
        assert self.filter.is_sponsored_link(url) is True

    def test_affiliate_parameter(self):
        """Test that affiliate parameters are detected."""
        url = "https://example.com/product?affiliate=partner"
        assert self.filter.is_sponsored_link(url) is True

    def test_sponsored_keyword_in_url(self):
        """Test that 'sponsored' keyword in URL is detected."""
        url = "https://example.com/sponsored/content"
        assert self.filter.is_sponsored_link(url) is True

    def test_ad_hashtag(self):
        """Test that #ad hashtag is detected."""
        url = "https://example.com/product#ad"
        assert self.filter.is_sponsored_link(url) is True

    def test_discount_code_keyword(self):
        """Test that discount code keyword is detected."""
        url = "https://example.com/checkout?discount code=SAVE20"
        assert self.filter.is_sponsored_link(url) is True

    def test_brilliant_org_domain(self):
        """Test that brilliant.org domain is blocked."""
        url = "https://brilliant.org/courses/python"
        assert self.filter.is_sponsored_link(url) is True

    def test_squarespace_domain(self):
        """Test that squarespace.com domain is blocked."""
        url = "https://squarespace.com/templates"
        assert self.filter.is_sponsored_link(url) is True

    def test_skillshare_domain(self):
        """Test that skillshare.com domain is blocked."""
        url = "https://skillshare.com/classes/python"
        assert self.filter.is_sponsored_link(url) is True

    def test_audible_domain(self):
        """Test that audible.com domain is blocked."""
        url = "https://audible.com/audiobooks"
        assert self.filter.is_sponsored_link(url) is True

    def test_www_prefix_removed(self):
        """Test that www. prefix is properly handled."""
        url = "https://www.brilliant.org/courses"
        assert self.filter.is_sponsored_link(url) is True

    def test_subdomain_matching(self):
        """Test that subdomains of blocked domains are caught."""
        url = "https://shop.amazon.com/product"
        assert self.filter.is_sponsored_link(url) is True

    def test_clean_link_not_flagged(self):
        """Test that clean links are not flagged."""
        url = "https://github.com/python/cpython"
        assert self.filter.is_sponsored_link(url) is False

    def test_clean_link_with_normal_query_params(self):
        """Test that clean links with normal params are not flagged."""
        url = "https://example.com/search?q=python&page=2"
        assert self.filter.is_sponsored_link(url) is False

    def test_case_insensitive_pattern_matching(self):
        """Test that pattern matching is case insensitive."""
        url = "https://example.com/content?UTM_SOURCE=newsletter"
        assert self.filter.is_sponsored_link(url) is True

    def test_case_insensitive_domain_matching(self):
        """Test that domain matching is case insensitive."""
        url = "https://WWW.BRILLIANT.ORG/courses"
        assert self.filter.is_sponsored_link(url) is True

    def test_malformed_url_not_flagged(self):
        """Test that malformed URLs don't cause crashes."""
        url = "not-a-valid-url"
        # Should not crash, err on side of not filtering
        assert self.filter.is_sponsored_link(url) is False

    def test_empty_url(self):
        """Test that empty URL is not flagged."""
        url = ""
        assert self.filter.is_sponsored_link(url) is False

    def test_filter_urls_removes_sponsored(self):
        """Test that filter_urls removes sponsored links."""
        urls = [
            "https://github.com/repo",
            "https://amzn.to/abc123",
            "https://example.com/article",
            "https://brilliant.org/course",
            "https://docs.python.org/3/",
        ]
        filtered = self.filter.filter_urls(urls)

        assert len(filtered) == 3
        assert "https://github.com/repo" in filtered
        assert "https://example.com/article" in filtered
        assert "https://docs.python.org/3/" in filtered
        assert "https://amzn.to/abc123" not in filtered
        assert "https://brilliant.org/course" not in filtered

    def test_filter_urls_with_context(self):
        """Test that filter_urls respects context for AWS links."""
        urls = [
            "https://amazon.com/books",
            "https://aws.amazon.com/s3/",
            "https://amazon.com/shopping",
        ]
        context = "AWS cloud storage solutions using S3"
        filtered = self.filter.filter_urls(urls, context)

        # AWS link should be kept due to context
        assert len(filtered) == 1
        assert "https://aws.amazon.com/s3/" in filtered

    def test_filter_urls_empty_list(self):
        """Test that filtering empty list returns empty list."""
        filtered = self.filter.filter_urls([])
        assert filtered == []

    def test_filter_urls_all_sponsored(self):
        """Test that filtering all sponsored links returns empty list."""
        urls = [
            "https://amzn.to/123",
            "https://brilliant.org/x",
            "https://example.com?utm_source=promo",
        ]
        filtered = self.filter.filter_urls(urls)
        assert filtered == []

    def test_filter_urls_none_sponsored(self):
        """Test that filtering no sponsored links returns original list."""
        urls = [
            "https://github.com/repo",
            "https://docs.python.org/3/",
            "https://example.com/article",
        ]
        filtered = self.filter.filter_urls(urls)
        assert len(filtered) == 3
        assert filtered == urls

    def test_custom_domains(self):
        """Test that custom domain list can be provided."""
        custom_filter = SponsoredFilter(sponsored_domains=["example.com"])

        assert custom_filter.is_sponsored_link("https://example.com/page") is True
        # Default domains should not be blocked with custom list
        assert custom_filter.is_sponsored_link("https://brilliant.org/course") is False

    def test_custom_patterns(self):
        """Test that custom pattern list can be provided."""
        custom_filter = SponsoredFilter(sponsored_patterns=[r"promo"])

        assert custom_filter.is_sponsored_link("https://example.com/promo") is True
        # Default patterns should not be matched with custom list
        assert custom_filter.is_sponsored_link("https://bit.ly/abc") is False

    def test_custom_domains_and_patterns(self):
        """Test that both custom domains and patterns can be provided."""
        custom_filter = SponsoredFilter(
            sponsored_domains=["custom.com"],
            sponsored_patterns=[r"promo"]
        )

        assert custom_filter.is_sponsored_link("https://custom.com/page") is True
        assert custom_filter.is_sponsored_link("https://example.com/promo") is True
        assert custom_filter.is_sponsored_link("https://brilliant.org/x") is False
        assert custom_filter.is_sponsored_link("https://bit.ly/x") is False

    def test_context_none_handling(self):
        """Test that None context is handled gracefully."""
        url = "https://amazon.com/product"
        assert self.filter.is_sponsored_link(url, None) is True

    def test_multiple_aws_keywords_in_context(self):
        """Test that multiple AWS keywords work in context for AWS URLs."""
        # Only actual AWS URLs should benefit from AWS context
        aws_url = "https://aws.amazon.com/lambda/"

        contexts = [
            "Using AWS Lambda functions",
            "Store files in S3 buckets",
            "Deploy EC2 instances",
            "Cloud computing with AWS",
        ]

        for context in contexts:
            assert self.filter.is_sponsored_link(aws_url, context) is False

        # Non-AWS amazon.com URLs should still be flagged even with AWS context
        product_url = "https://amazon.com/product"
        assert self.filter.is_sponsored_link(product_url, "Using AWS Lambda") is True

    def test_exact_domain_match(self):
        """Test that exact domain matching works."""
        # amazon.com should match
        assert self.filter.is_sponsored_link("https://amazon.com/x") is True
        # but not-amazon.com should not
        assert self.filter.is_sponsored_link("https://not-amazon.com/x") is False

    def test_hash_ad_word_boundary(self):
        """Test that #ad requires word boundary."""
        # #ad should match
        assert self.filter.is_sponsored_link("https://example.com#ad") is True
        # but #addon should not
        assert self.filter.is_sponsored_link("https://example.com#addon") is False

    def test_pattern_in_path(self):
        """Test that patterns match in URL path."""
        url = "https://example.com/sponsored/content/article"
        assert self.filter.is_sponsored_link(url) is True

    def test_pattern_in_query(self):
        """Test that patterns match in query string."""
        url = "https://example.com/article?sponsored=true"
        assert self.filter.is_sponsored_link(url) is True

    def test_pattern_in_fragment(self):
        """Test that patterns match in fragment."""
        url = "https://example.com/article#sponsored-section"
        assert self.filter.is_sponsored_link(url) is True

    def test_real_world_youtube_sponsor_link(self):
        """Test real-world YouTube sponsor link pattern."""
        url = "https://brilliant.org/3blue1brown"
        assert self.filter.is_sponsored_link(url) is True

    def test_real_world_newsletter_link(self):
        """Test real-world newsletter tracking link."""
        url = "https://example.com/article?utm_source=newsletter&utm_medium=email&utm_campaign=weekly"
        assert self.filter.is_sponsored_link(url) is True

    def test_real_world_affiliate_amazon_link(self):
        """Test real-world Amazon affiliate link."""
        url = "https://www.amazon.com/dp/B08X1234/?tag=myaffiliate-20&ref=as_li_ss_tl"
        assert self.filter.is_sponsored_link(url) is True
