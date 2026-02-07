
import unittest
from thefuzz import process

# This is the dictionary from the main script
category_aliases = {
    "Dining": "Restaurants",
    "Restaurants": "Restaurants",
    "Gas": "Gas",
    "Grocery Stores": "Grocery Stores",
    "Groceries": "Grocery Stores",
    "Travel": "Travel",
    "Transit": "Transit",
    "Streaming": "Streaming",
    "Drugstores": "Drugstores",
    "Home Improvement": "Home Improvement",
    "Home Improvement Stores": "Home Improvement",
    "Gym": "Fitness Clubs",
    "Entertainment": "Live Entertainment"
}

def normalize_category(scraped_category, aliases):
    """
    Finds the best match for a scraped category from the aliases dictionary.
    """
    match, score = process.extractOne(scraped_category, aliases.keys())
    if score > 70:
        return aliases[match]
    return scraped_category # Return original if no good match

class TestFuzzyMatching(unittest.TestCase):

    def test_exact_match(self):
        """Tests a category that is an exact match."""
        scraped = "Streaming"
        expected = "Streaming"
        self.assertEqual(normalize_category(scraped, category_aliases), expected)

    def test_close_match(self):
        """Tests a category that is a close match."""
        scraped = "Select Streaming Services"
        expected = "Streaming"
        self.assertEqual(normalize_category(scraped, category_aliases), expected)

    def test_different_match(self):
        """Tests a category that is a slightly different match."""
        scraped = "Restaurant"
        expected = "Restaurants"
        self.assertEqual(normalize_category(scraped, category_aliases), expected)

    def test_no_match(self):
        """Tests a category that should not be matched."""
        scraped = "Car Washes"
        expected = "Car Washes"
        self.assertEqual(normalize_category(scraped, category_aliases), expected)
        
    def test_another_close_match(self):
        """Tests another close match."""
        scraped = "Groceries"
        expected = "Grocery Stores"
        self.assertEqual(normalize_category(scraped, category_aliases), expected)
        
    def test_dining_to_restaurants_match(self):
        """Tests if 'Dining' correctly maps to 'Restaurants'."""
        scraped = "Dining"
        expected = "Restaurants"
        self.assertEqual(normalize_category(scraped, category_aliases), expected)

if __name__ == '__main__':
    unittest.main()
